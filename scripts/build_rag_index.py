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

# Chunker schema version. BUMP this whenever the chunking strategy changes
# (and keep generators/rag_retriever.py::_EXPECTED_CHUNKER_VERSION in sync).
# After a successful build it is written to <index>/chunker_version.txt; the
# retriever warns when the on-disk index was built by a different version,
# so a stale index after a chunking change can't masquerade as healthy
# (Codex review 2026-06-15, finding #3).
_CHUNKER_VERSION = "2026-06-15-per-example"
_VERSION_SENTINEL = "chunker_version.txt"


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


def _load_learning_chunks(source_path: Path) -> list[Chunk]:
    """Finer-grained chunking for the auto-generated learning files
    (quality_successes.md / quality_anti_patterns.md).

    Why (audited 2026-06-15): these files mix two kinds of H2 section —
      * aggregate stats ("採用すべきタイトル型: ブラケット無し 10件…") —
        meta-text that no topical query matches above the 0.55 floor, and
      * concrete title examples ("- [【保存版】韓国コスメ成分の正解…](♥4)") —
        each example IS topic-bearing, so a related new topic SHOULD be
        able to retrieve it.
    The whole-H2 chunking (_load_chunks) buried the topical examples inside
    a stat-heavy blob, so _build_rag_learned_block scored 0 hits and always
    fell back to the static block ([rag-learn]=0 in the 6-15 generate log).

    Here each concrete example bullet becomes its own chunk (the H2 title is
    kept as context so マネすべき / 避けるべき polarity stays attached);
    stat / prose sections stay whole. Used ONLY for the two learning
    collections — hallucinations / ops_incidents / generation_guides keep
    _load_chunks so their long-tuned retrieval behaviour is untouched.
    """
    if not source_path.exists():
        print(f"  WARN: {source_path} missing — skipped")
        return []
    raw = source_path.read_text(encoding="utf-8")
    chunks: list[Chunk] = []
    idx = 0

    def _emit(text: str, title: str) -> None:
        nonlocal idx
        chunks.append(Chunk(
            text=text,
            section_title=title,
            section_index=idx,
            source_file=source_path.name,
        ))
        idx += 1

    for title, body in _split_h2_sections(raw):
        lines = body.splitlines()
        bullets = [
            ln.strip() for ln in lines if ln.strip().startswith("- ")
        ]
        # A bullet is "example-like" when it carries an engagement marker
        # (♥) or is a bracketed title link ("- [..."). Stat bullets like
        # "- ブラケット無し: 10件" have neither.
        example_bullets = [
            b for b in bullets if "♥" in b or b.startswith("- [")
        ]
        # Split into per-example chunks when this H2 is an example list:
        # its title says 例 (split even a single example), or most of its
        # bullets are concrete examples (robust to title-wording drift).
        is_example_section = bool(
            ("例" in title and example_bullets)
            or (
                len(example_bullets) >= 2
                and len(example_bullets) >= len(bullets) / 2
            )
        )
        if is_example_section:
            for b in example_bullets:
                _emit(f"## {title}\n{b}", title)
            # Preserve everything that ISN'T an example bullet — trailing
            # directive prose ("...避けるか別の切り口で書き直すこと") and any
            # non-example stat bullets — as one residual chunk, so no
            # guidance is dropped from the index (Codex review 2026-06-15).
            residual = "\n".join(
                ln for ln in lines
                if ln.strip() and ln.strip() not in example_bullets
            ).strip()
            if residual:
                _emit(f"## {title}\n{residual}", title)
        else:
            _emit(f"## {title}\n{body}", title)
    return chunks


def _load_past_article_chunks() -> list[Chunk]:
    """Build chunks from data/articles/*.json — one per article.

    Each chunk = title + first 300 chars of summary/content. Lean by
    design: duplicate detection only needs topic-level similarity, not
    surface-text matching. Skips placeholder/empty files.
    """
    import json as _json
    chunks: list[Chunk] = []
    articles_dir = _REPO / "data" / "articles"
    if not articles_dir.exists():
        print(f"  WARN: {articles_dir} missing — past_articles skipped")
        return []
    files = sorted(articles_dir.glob("*.json"))
    for i, fp in enumerate(files):
        try:
            data = _json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            continue
        title = (data.get("title") or "").strip()
        if not title:
            continue
        body = (
            data.get("summary")
            or (data.get("content") or "")[:600]
        ).strip()
        text = f"# {title}\n{body[:300]}"
        chunks.append(
            Chunk(
                text=text,
                section_title=title[:80],
                section_index=i,
                source_file=fp.name,
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
    # Use enumerate-over-chunks so IDs are unique even when the same
    # collection is built from multiple source files (each file resets
    # section_index to 0, which would collide on insert).
    ids = [f"{collection_name}-{i:04d}" for i in range(len(chunks))]
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
        # 2026-05-14: ops_incidents — operational rework (orphan publish,
        # selector drift, env-var syntax traps, MD5-identical "ChatGPT
        # images", etc.). Separate from hallucinations because these are
        # tooling / flow bugs, not content fabrication. Indexed so the
        # next session can semantically query "edit_article paid article
        # not saving" and surface the 有料エリア設定 fix.
        ("ops_incidents", _REPO / "docs/knowledge/ops_incidents.md"),
    ]
    # The two auto-generated learning files get finer per-example chunking
    # so concrete title examples become individually retrievable; every
    # other collection keeps the long-tuned whole-H2 chunking.
    _LEARNING_COLLECTIONS = {"anti_patterns", "successes"}
    total = 0
    for collection_name, source_path in plan:
        if collection_name in _LEARNING_COLLECTIONS:
            chunks = _load_learning_chunks(source_path)
        else:
            chunks = _load_chunks(source_path)
        count = _build_collection(client, model, collection_name, chunks)
        print(f"  {collection_name}: {count} chunk(s) from {source_path.name}")
        total += count

    # 2026-05-11 Sprint 6: generation_guides collection — strategy /
    # rule documents the writer + image + monetization paths can pull
    # selectively. Intentionally excludes daily auto_learning snapshots
    # and quality_insights_*.md (those are noise without consolidation).
    # Hard rules stay in prompts.yaml (always-loaded), this is for
    # softer guides the LLM can reference contextually.
    guide_files = [
        _REPO / "docs/knowledge/image-generation/2026-04-08_options_comparison.md",
        _REPO / "docs/knowledge/monetization/2026-04-08_note_basics.md",
        _REPO / "docs/knowledge/affiliate_strategies/2026-04-13_research.md",
        _REPO / "docs/knowledge/note-trends/prompt_suggestions.md",
        _REPO / "docs/knowledge/note-trends/learning_strategy.md",
        _REPO / "docs/knowledge/note-trends/paid_analysis.md",
        _REPO / "docs/knowledge/note-trends/top_authors.md",
        _REPO / "docs/knowledge/note-trends/2026-04-09_intro_patterns.md",
        _REPO / "docs/knowledge/note-trends/2026-04-09_monetization_methods.md",
        _REPO / "docs/knowledge/note-trends/2026-04-09_monetize_ai_focus.md",
        _REPO / "docs/knowledge/quality_codex_grounded_scoring.md",
        _REPO / "docs/knowledge/quality_recurring_failures.md",
        _REPO / "docs/membership_plans/01_ai_sidejob_lab.md",
        _REPO / "docs/membership_plans/02_kbeauty_trend_circle.md",
    ]
    guide_chunks: list[Chunk] = []
    for fp in guide_files:
        loaded = _load_chunks(fp)
        guide_chunks.extend(loaded)
    g_count = _build_collection(client, model, "generation_guides", guide_chunks)
    print(f"  generation_guides: {g_count} chunk(s) from {len(guide_files)} source file(s)")
    total += g_count

    # Sprint 3 (2026-05-11): past_articles collection for duplicate
    # detection on new topic seeding. Indexed from data/articles/*.json,
    # each article becomes ONE chunk: title + summary (or content head).
    # We deliberately skip full content to keep the index lean and
    # focused on topic similarity rather than surface phrasing.
    article_chunks = _load_past_article_chunks()
    pa_count = _build_collection(client, model, "past_articles", article_chunks)
    print(f"  past_articles: {pa_count} chunk(s) from data/articles/*.json")
    total += pa_count

    # 2026-05-11 PM: thumbnail_styles collection — each game-homage
    # style becomes ONE chunk whose embedding represents the article
    # types it fits. Allows pick_style_for_article() to do semantic
    # auto-selection (副業達成 → hunt_success, 比較 → ready_fight, etc.)
    # rather than the older SHA-256 random pick.
    style_chunks: list[Chunk] = []
    try:
        from generators.game_homage_styles import _STYLES
        for i, style in enumerate(_STYLES):
            fit_hint = style.get("fit_hint") or ""
            text = (
                f"## {style['name']}\n"
                f"用途: {fit_hint}\n"
                # Include a digest of the visual block so the query embedding
                # picks up on the visual feel too — helps when a query is
                # phrased visually ("派手なネオン" → rhythm_perfect 等).
                f"視覚: {style.get('style_block','')[:200]}"
            )
            style_chunks.append(Chunk(
                text=text,
                section_title=style["name"],  # critical: name is the key for lookup
                section_index=i,
                source_file="game_homage_styles.py",
            ))
    except Exception as exc:
        print(f"  WARN: thumbnail_styles unavailable: {exc}")
    ts_count = _build_collection(client, model, "thumbnail_styles", style_chunks)
    print(f"  thumbnail_styles: {ts_count} chunk(s) from generators/game_homage_styles.py")
    total += ts_count
    # Stamp the index with the chunker version so the retriever can detect
    # a stale on-disk index after a chunking-strategy change.
    try:
        (_INDEX_PATH / _VERSION_SENTINEL).write_text(
            _CHUNKER_VERSION, encoding="utf-8",
        )
    except OSError as exc:
        print(f"  WARN: could not write version sentinel: {exc}")
    print(f"DONE - total chunks indexed: {total} (chunker {_CHUNKER_VERSION})")
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
