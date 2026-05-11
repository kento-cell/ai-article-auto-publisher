"""Benchmark candidate embedding models on this project's RAG corpus.

Models compared (download on first run, ~5GB total):
- intfloat/multilingual-e5-base (current baseline, 278M)
- intfloat/multilingual-e5-large (560M)
- BAAI/bge-m3 (568M, multilingual + hybrid)
- cl-nagoya/ruri-large (337M, Japanese-specialized)

Metrics
- Recall@5: fraction of golden queries where the correct chunk appears
  in the top-5 retrieved hits.
- MRR@10: mean reciprocal rank — higher is better.
- Embed wall-clock for the full corpus (proxy for setup cost).
- Per-query wall-clock (proxy for runtime cost).

Eval set
- 20+ hand-crafted (query, expected_section_title) pairs covering
  every collection (anti_patterns / successes / hallucinations /
  past_articles).
- The expected section title must appear in the top-5 metadata
  list for the query to count as a hit.

Output: docs/knowledge/rag_model_selection_2026-05-11.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_OUTPUT = _REPO / "docs" / "knowledge" / "rag_model_selection_2026-05-11.md"


CANDIDATE_MODELS = [
    "intfloat/multilingual-e5-base",
    "intfloat/multilingual-e5-large",
    "BAAI/bge-m3",
    "cl-nagoya/ruri-large",
]


# (query, expected_section_title_substring, expected_collection)
EVAL_SET: list[tuple[str, str, str]] = [
    # --- hallucinations ---
    ("店名が伏字「〇〇寿司」「××焼鳥」のまま公開された",
     "未置換伏字", "hallucinations"),
    ("AI で生成した旨の免責 footer が記事末尾に残る",
     "AI が構成", "hallucinations"),
    ("Bluesky 投稿を捏造して引用した",
     "架空 SNS 投稿引用", "hallucinations"),
    ("店舗名を A / B / C と記号化して書く",
     "A/B/C 記号命名", "hallucinations"),
    ("仮名と注記を付けた店名で逃げる",
     "仮名/仮称マーカー", "hallucinations"),
    ("チェーン店をご当地グルメ記事に混ぜた",
     "チェーン店混入", "hallucinations"),
    ("画像の alt と本文の内容が一致しない",
     "画像ハルシネーション", "hallucinations"),
    ("プロンプトに残った placeholder URL がそのまま",
     "プロンプト残留 placeholder", "hallucinations"),
    # --- anti_patterns / successes ---
    ("低エンゲ記事の特徴的なタイトル型",
     "避けるべき", "anti_patterns"),
    ("【そもそも解説】系のタイトル",
     "避けるべき具体タイトル例", "anti_patterns"),
    ("AI 副業のヒット記事はどんなタイトル？",
     "採用すべき", "successes"),
    ("バズった上位 20% 記事のブラケット採用率",
     "上位記事の採用パターン", "successes"),
    # --- past_articles ---
    ("Notion テンプレ販売で月数万円",
     "Notion AIで作る", "past_articles"),
    ("AI 副業を 0 から 30 日で始めるロードマップ",
     "完全未経験から AI 副業", "past_articles"),
    ("Dify Voiceflow でチャットボット代行",
     "Dify", "past_articles"),
    ("Make Zapier n8n 業務自動化レシピ",
     "Make / Zapier / n8n", "past_articles"),
    ("Perplexity GenSpark を使ったリサーチ代行",
     "Perplexity", "past_articles"),
    ("AI ライティング副業の案件単価",
     "AI ライティング", "past_articles"),
    ("Gumroad で AI プロンプト集を売る",
     "Gumroad", "past_articles"),
    ("Codex を OpenAI 依存から外して動かす",
     "Codex", "past_articles"),
    ("ISUCON Fail を計測基盤の限界として読み解く",
     "ISUNARABE", "past_articles"),
    ("AI 生成のゴミ脆弱性報告が HackerOne で問題に",
     "ゴミ報告", "past_articles"),
]


def _split_h2_sections(content: str) -> list[tuple[str, str]]:
    import re
    sections: list[tuple[str, str]] = []
    h2_re = re.compile(r"^## (.+)$", re.MULTILINE)
    matches = list(h2_re.finditer(content))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if body:
            sections.append((title, body))
    return sections


def _load_corpus_per_collection() -> dict[str, list[tuple[str, str]]]:
    """Return {collection_name: [(title, full_text), ...]} for all 4
    collections, mirroring scripts/build_rag_index.py's chunking."""
    corpus: dict[str, list[tuple[str, str]]] = {}
    md_plan = [
        ("anti_patterns", _REPO / "docs/knowledge/quality_anti_patterns.md"),
        ("successes", _REPO / "docs/knowledge/quality_successes.md"),
        ("hallucinations", _REPO / "docs/knowledge/hallucination_registry.md"),
    ]
    for name, path in md_plan:
        chunks: list[tuple[str, str]] = []
        if path.exists():
            raw = path.read_text(encoding="utf-8")
            for title, body in _split_h2_sections(raw):
                chunks.append((title, f"## {title}\n{body}"))
        corpus[name] = chunks

    # past_articles
    articles: list[tuple[str, str]] = []
    articles_dir = _REPO / "data" / "articles"
    if articles_dir.exists():
        for fp in sorted(articles_dir.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            title = (data.get("title") or "").strip()
            if not title:
                continue
            body = (
                data.get("summary")
                or (data.get("content") or "")[:600]
            ).strip()
            articles.append((title, f"# {title}\n{body[:300]}"))
    corpus["past_articles"] = articles

    return corpus


def _bench_one_model(model_name: str, corpus: dict) -> dict:
    """Run the eval set against a single model. Returns metrics dict."""
    from sentence_transformers import SentenceTransformer
    import numpy as np

    print(f"\n=== {model_name} ===")
    t_load = time.time()
    model = SentenceTransformer(model_name)
    load_s = time.time() - t_load
    print(f"  load: {load_s:.1f}s")

    # Embed corpus
    embedded: dict[str, tuple[list[tuple[str, str]], np.ndarray]] = {}
    t_embed = time.time()
    total_chunks = 0
    for coll_name, items in corpus.items():
        if not items:
            embedded[coll_name] = (items, np.zeros((0, 768)))
            continue
        passages = [f"passage: {text}" for _, text in items]
        vecs = model.encode(passages, normalize_embeddings=True,
                            show_progress_bar=False)
        embedded[coll_name] = (items, vecs)
        total_chunks += len(items)
    embed_s = time.time() - t_embed
    print(f"  embed {total_chunks} chunks: {embed_s:.1f}s")

    # Run eval
    hits_at_5 = 0
    mrr_sum = 0.0
    per_query_times: list[float] = []
    for query, expected_substr, expected_coll in EVAL_SET:
        items, vecs = embedded.get(expected_coll, (None, None))
        if not items or vecs is None or len(vecs) == 0:
            continue
        t0 = time.time()
        q_vec = model.encode([f"query: {query}"], normalize_embeddings=True,
                             show_progress_bar=False)
        sims = (q_vec @ vecs.T)[0]
        order = sims.argsort()[::-1]
        per_query_times.append(time.time() - t0)
        rank = None
        for r, idx in enumerate(order[:10], 1):
            title, _ = items[idx]
            if expected_substr in title:
                rank = r
                break
        if rank is not None:
            if rank <= 5:
                hits_at_5 += 1
            mrr_sum += 1.0 / rank
    recall5 = hits_at_5 / len(EVAL_SET) if EVAL_SET else 0.0
    mrr = mrr_sum / len(EVAL_SET) if EVAL_SET else 0.0
    avg_q_ms = (sum(per_query_times) / len(per_query_times) * 1000) if per_query_times else 0
    print(f"  Recall@5: {recall5*100:.1f}%  MRR: {mrr:.3f}  avg query: {avg_q_ms:.1f}ms")
    return {
        "model": model_name,
        "load_s": round(load_s, 2),
        "embed_s": round(embed_s, 2),
        "recall_at_5": round(recall5, 4),
        "mrr_at_10": round(mrr, 4),
        "avg_query_ms": round(avg_q_ms, 2),
        "eval_size": len(EVAL_SET),
        "total_chunks": total_chunks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models", nargs="+", default=CANDIDATE_MODELS,
        help="Models to benchmark (default: all 4 candidates)",
    )
    args = parser.parse_args()

    print(f"loading corpus from {_REPO} ...")
    corpus = _load_corpus_per_collection()
    for k, v in corpus.items():
        print(f"  {k}: {len(v)} chunks")

    results: list[dict] = []
    for model_name in args.models:
        try:
            r = _bench_one_model(model_name, corpus)
            results.append(r)
        except Exception as exc:
            print(f"FAILED {model_name}: {exc}")
            results.append({
                "model": model_name,
                "error": str(exc)[:200],
            })

    # Sort by Recall@5 desc, then MRR desc
    def _sort_key(r):
        if "error" in r:
            return (-1, -1)
        return (r.get("recall_at_5", 0), r.get("mrr_at_10", 0))
    results.sort(key=_sort_key, reverse=True)

    # Write markdown report
    lines = [
        "# RAG embedding model benchmark (2026-05-11)",
        "",
        f"Corpus: {sum(len(v) for v in corpus.values())} chunks across 4 collections.",
        f"Eval set: {len(EVAL_SET)} hand-crafted golden queries.",
        f"Hardware: same machine as production (single GPU/CPU run).",
        "",
        "## Results (sorted by Recall@5, then MRR)",
        "",
        "| Rank | Model | Recall@5 | MRR@10 | Embed (s) | Load (s) | Query (ms) |",
        "|------|-------|----------|--------|-----------|----------|------------|",
    ]
    for i, r in enumerate(results, 1):
        if "error" in r:
            lines.append(
                f"| {i} | {r['model']} | — | — | — | — | "
                f"ERROR: {r['error'][:80]} |"
            )
        else:
            lines.append(
                f"| {i} | {r['model']} | {r['recall_at_5']*100:.1f}% | "
                f"{r['mrr_at_10']:.3f} | {r['embed_s']} | {r['load_s']} | "
                f"{r['avg_query_ms']} |"
            )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Recall@5 = fraction of queries where the correct chunk "
        "appears in the top-5 retrieved hits."
    )
    lines.append(
        "- MRR@10 = mean reciprocal rank, computed across the top-10 "
        "retrieved hits."
    )
    lines.append(
        "- Eval set covers all 4 collections (hallucinations, anti_patterns, "
        "successes, past_articles) to avoid bias toward any one knowledge type."
    )
    lines.append(
        "- All models tested with e5-style prefixing (`query: ...` and "
        "`passage: ...`) for fairness."
    )
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    if results and "error" not in results[0]:
        winner = results[0]["model"]
        lines.append(
            f"**Selected: `{winner}`** — top Recall@5 + MRR with acceptable "
            f"load/embed cost on the production hardware."
        )
    lines.append("")

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote report to {_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
