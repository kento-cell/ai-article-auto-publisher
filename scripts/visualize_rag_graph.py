"""Obsidian-graph-view-style visualiser for the chromadb RAG index.

The vectors are 768-dim (multilingual-e5-base) — you can't see 768 dimensions
directly. This builds the same thing Obsidian's graph view shows: a
force-directed node-link graph where each node is a chunk and an edge links
two chunks whose embeddings are similar (cosine kNN). Nodes are coloured by
collection and seeded with a t-SNE 2D projection so clusters are spatially
meaningful even before the physics settles.

Output: a self-contained interactive HTML (vis-network from CDN — needs
internet on first open). Drag nodes, zoom, hover for the chunk text.

    PYTHONIOENCODING=utf-8 py scripts/visualize_rag_graph.py
    PYTHONIOENCODING=utf-8 py scripts/visualize_rag_graph.py --neighbors 5 --min-sim 0.62
    PYTHONIOENCODING=utf-8 py scripts/visualize_rag_graph.py --collections successes,anti_patterns,past_articles
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

_INDEX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag_index"
)

# Distinct, legible colours per collection.
_PALETTE = {
    "past_articles":      "#4e79a7",
    "generation_guides":  "#59a14f",
    "hallucinations":     "#e15759",
    "ops_incidents":      "#f28e2b",
    "thumbnail_styles":   "#b07aa1",
    "successes":          "#76b7b2",
    "anti_patterns":      "#edc948",
}
_FALLBACK = "#9c9c9c"


def _load(collections: list[str] | None):
    import chromadb
    client = chromadb.PersistentClient(path=_INDEX_PATH)
    names = [c.name for c in client.list_collections()]
    if collections:
        names = [n for n in names if n in collections]
    vecs, labels, texts = [], [], []
    for name in names:
        col = client.get_collection(name)
        got = col.get(include=["embeddings", "documents"])
        embs = got.get("embeddings")
        docs = got.get("documents")
        embs = [] if embs is None else list(embs)
        docs = [] if docs is None else list(docs)
        for emb, doc in zip(embs, docs):
            vecs.append(emb)
            labels.append(name)
            # strip the e5 "passage:" prefix and tidy whitespace for hover
            t = (doc or "").replace("passage: ", "").replace("\n", " ").strip()
            texts.append(t)
    return np.asarray(vecs, dtype=np.float32), labels, texts


def _build(vecs, labels, texts, neighbors: int, min_sim: float, layout: str):
    from sklearn.neighbors import NearestNeighbors

    n = len(vecs)
    # Normalise so dot product == cosine similarity.
    norm = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)

    # 2D seed positions for a meaningful initial layout.
    if layout == "pca" or n < 6:
        from sklearn.decomposition import PCA
        xy = PCA(n_components=2, random_state=0).fit_transform(norm)
    else:
        from sklearn.manifold import TSNE
        perp = max(5, min(30, (n - 1) // 3))
        xy = TSNE(
            n_components=2, perplexity=perp, init="pca",
            random_state=0, max_iter=600,
        ).fit_transform(norm)
    # Scale to a comfortable canvas range.
    xy = xy - xy.mean(axis=0)
    span = np.abs(xy).max() or 1.0
    xy = xy / span * 900.0

    # kNN edges by cosine similarity (skip self).
    k = min(neighbors + 1, n)
    nn = NearestNeighbors(n_neighbors=k, metric="cosine").fit(norm)
    dist, idx = nn.kneighbors(norm)

    seen: set[tuple[int, int]] = set()
    edges = []
    for i in range(n):
        for j, d in zip(idx[i][1:], dist[i][1:]):
            sim = 1.0 - float(d)
            if sim < min_sim:
                continue
            a, b = (i, int(j)) if i < int(j) else (int(j), i)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            edges.append({"from": a, "to": b, "value": round(sim, 3)})

    deg = [0] * n
    for e in edges:
        deg[e["from"]] += 1
        deg[e["to"]] += 1

    nodes = []
    for i in range(n):
        snippet = texts[i][:140]
        nodes.append({
            "id": i,
            "label": "",  # keep the canvas clean; identity shows on hover
            "title": f"[{labels[i]}]  {html.escape(snippet)}",
            "color": _PALETTE.get(labels[i], _FALLBACK),
            "x": float(xy[i][0]),
            "y": float(xy[i][1]),
            "size": 6 + min(18, deg[i] * 1.5),
            "group": labels[i],
        })
    return nodes, edges


_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>RAG vector graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
 html,body{{margin:0;height:100%;background:#16181d;color:#e6e6e6;font-family:system-ui,sans-serif}}
 #net{{width:100%;height:100vh}}
 #legend{{position:fixed;top:10px;left:10px;background:#1f2228cc;padding:10px 12px;border-radius:8px;font-size:13px;line-height:1.7}}
 #legend b{{display:block;margin-bottom:4px;font-size:12px;color:#aaa;font-weight:600}}
 .sw{{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
 #hud{{position:fixed;bottom:10px;left:10px;background:#1f2228cc;padding:8px 12px;border-radius:8px;font-size:12px;color:#bbb}}
</style></head><body>
<div id="legend"><b>collections</b>{legend}</div>
<div id="hud">{n} chunks · {m} similarity links · drag / scroll-zoom / hover for text</div>
<div id="net"></div>
<script>
const nodes=new vis.DataSet({nodes});
const edges=new vis.DataSet({edges});
new vis.Network(document.getElementById('net'),{{nodes,edges}},{{
 nodes:{{shape:'dot',borderWidth:0,font:{{color:'#ddd'}}}},
 edges:{{color:{{color:'#3a3f4b',highlight:'#8ab4f8'}},width:0.4,smooth:false}},
 physics:{{solver:'barnesHut',stabilization:{{iterations:250}},
   barnesHut:{{gravitationalConstant:-3000,springLength:90,springConstant:0.02,damping:0.4}}}},
 interaction:{{hover:true,tooltipDelay:80,hideEdgesOnDrag:true}}
}});
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--neighbors", type=int, default=4, help="kNN edges per node")
    ap.add_argument("--min-sim", type=float, default=0.6, help="min cosine to draw an edge")
    ap.add_argument("--layout", choices=["tsne", "pca"], default="tsne")
    ap.add_argument("--collections", default="", help="comma list to restrict (default: all)")
    ap.add_argument("--out", default="data/rag_graph.html")
    args = ap.parse_args()

    cols = [c.strip() for c in args.collections.split(",") if c.strip()] or None
    print("loading vectors from chromadb ...")
    vecs, labels, texts = _load(cols)
    if not len(vecs):
        print("no vectors found — build the index first (scripts/build_rag_index.py)")
        return 1
    print(f"  {len(vecs)} vectors, dim={vecs.shape[1]}, "
          f"collections={sorted(set(labels))}")
    print(f"projecting ({args.layout}) + building kNN graph ...")
    nodes, edges = _build(vecs, labels, texts, args.neighbors, args.min_sim, args.layout)

    present = [c for c in _PALETTE if c in set(labels)]
    legend = "".join(
        f'<div><span class="sw" style="background:{_PALETTE[c]}"></span>'
        f'{c} ({labels.count(c)})</div>' for c in present
    )
    out_html = _HTML.format(
        legend=legend, n=len(nodes), m=len(edges),
        nodes=json.dumps(nodes, ensure_ascii=False),
        edges=json.dumps(edges, ensure_ascii=False),
    )
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_html)
    print(f"wrote {out_path}  ({len(nodes)} nodes, {len(edges)} edges)")
    print("open it in a browser (needs internet for the vis-network CDN).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
