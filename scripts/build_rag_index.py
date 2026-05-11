"""Build the chromadb RAG index from project knowledge files.

Sprint 1 (2026-05-11): three collections to start —

- ``anti_patterns``  ← docs/knowledge/quality_anti_patterns.md
- ``successes``      ← docs/knowledge/quality_successes.md
- ``hallucinations`` ← docs/knowledge/hallucination_registry.md

Usage::

    py scripts/build_rag_index.py             # full rebuild
    py scripts/build_rag_index.py --test      # rebuild + sample queries

The script is idempotent: each run deletes and recreates the three
collections so re-running after editing the source markdown produces
a consistent fresh index. Index lives at ``data/rag_index/``.

Chunking strategy:
- For *_patterns.md / successes.md: each H2 section becomes one chunk
  (they're already short and topic-coherent — splitting finer dilutes
  context).
- For hallucination_registry.md: each numbered ``## N. ...`` incident
  becomes one chunk. Summary table and operations-rule sections are
  embedded as separate "meta" chunks so a query like "how do we
  manage forbidden_phrases?" can also hit operational guidance.

Metadata attached per chunk: ``source_file``, ``section_title``,
``section_index`` (ordinal), ``category`` (collection name).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_INDEX_PATH = _REPO / "data" / "rag_index"
_MODEL_NAME = "intfloat/multilingual-e5-base"


@dataclass
class Chunk:
    text: str
    section_title: str
    section_index: int
    source_file: str


def _split_h2_sections(content: str) -> list[tuple[str, str]]:
    """Split a markdown document at H2 headings.

    Returns a list of ``(section_title, section_body)`` tuples. The
    section title is the H2 line stripped of ``## ``; the body is the
    raw markdown between this H2 and the next H2 (or EOF). Content
    before the first H2 is dropped — it's typically the H1 title and
    a one-line description.
    """
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


def _load_chunks(source_path: Path) -> list[Chunk]:
    if not source_path.exists():
        print(f"  WARN: {source_path} missing — skipped")
        return []
    raw = source_path.read_text(encoding="utf-8")
    sections = _split_h2_sections(raw)
    chunks: list[Chunk] = []
    for i, (title, body) in enumerate(sections):
        # Prepend the section title so retrieval can match on it
        # too — "## A/B/C 記号命名" + body is more searchable than
        # body alone.
        full = f"## {title}\n{body}"
        chunks.append(
            Chunk(
                text=full,
                section_title=title,
                section_index=i,
                source_file=source_path.name,
            ),
        )
    return chunks


def _build_collection(
    client, model, collection_name: str, chunks: list[Chunk],
) -> int:
    # Drop + recreate so re-runs reflect upstream markdown edits.
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    coll = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "l2"},
    )
    if not chunks:
        return 0
    # e5 passage prefix for asymmetric query/document encoding.
    passages = [f"passage: {c.text}" for c in chunks]
    embeddings = model.encode(passages, normalize_embeddings=True).tolist()
    ids = [f"{collection_name}-{c.section_index:03d}" for c in chunks]
    metadatas = [
        {
            "source_file": c.source_file,
            "section_title": c.section_title,
            "section_index": c.section_index,
            "category": collection_name,
        }
        for c in chunks
    ]
    coll.add(
        ids=ids,
        embeddings=embeddings,
        documents=passages,
        metadatas=metadatas,
    )
    return len(chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test", action="store_true",
        help="After build, run sample queries against each collection",
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Wipe the entire index directory before building",
    )
    args = parser.parse_args()

    if args.rebuild and _INDEX_PATH.exists():
        shutil.rmtree(_INDEX_PATH)
        print(f"wiped {_INDEX_PATH}")

    print("loading embedding model ...")
    from sentence_transformers import SentenceTransformer
    import chromadb
    model = SentenceTransformer(_MODEL_NAME)
    client = chromadb.PersistentClient(path=str(_INDEX_PATH))

    plan = [
        ("anti_patterns", _REPO / "docs/knowledge/quality_anti_patterns.md"),
        ("successes", _REPO / "docs/knowledge/quality_successes.md"),
        ("hallucinations", _REPO / "docs/knowledge/hallucination_registry.md"),
    ]
    total = 0
    for collection_name, source_path in plan:
        chunks = _load_chunks(source_path)
        count = _build_collection(client, model, collection_name, chunks)
        print(f"  {collection_name}: {count} chunk(s) from {source_path.name}")
        total += count
    print(f"DONE - total chunks indexed: {total}")
    print(f"index: {_INDEX_PATH}")

    if args.test:
        print("\n--- sample queries ---")
        from generators.rag_retriever import RagRetriever
        r = RagRetriever()
        samples = [
            ("AI副業 ライティング", "anti_patterns", 3),
            ("AI副業 ライティング", "successes", 3),
            ("伏字 店名", "hallucinations", 3),
            ("画像 ハルシネーション", "hallucinations", 2),
        ]
        for q, coll, k in samples:
            print(f"\n[Q: {q!r} -> {coll}, top={k}]")
            hits = r.retrieve(q, coll, top_k=k)
            if not hits:
                print("  (no hits)")
                continue
            for h in hits:
                snippet = h.text[:120].replace("\n", " ")
                print(f"  [{h.score:.3f}] {snippet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
