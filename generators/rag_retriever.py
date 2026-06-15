"""RAG retriever — semantic search over the project's evergreen knowledge.

Sprint 1 (2026-05-11): wraps a chromadb on-disk index with a sentence-
transformers embedder and exposes a single ``retrieve`` API. Today's
collections:

- ``anti_patterns``  — engagement-bottom-20% patterns to avoid
- ``successes``      — engagement-top-20% patterns to mimic
- ``hallucinations`` — past hallucination incidents to defend against

The retriever is INTENTIONALLY NOT wired into ``main.py`` yet — this
file just defines the contract. Sprint 2 will gate it behind an env
flag and replace the static ``_load_learned_block`` injection.

Design notes
------------
- Embedding model: ``intfloat/multilingual-e5-base`` (~280MB, 768-dim).
  e5-base is the sweet spot for Japanese on this hardware — e5-large
  pushes memory pressure during Gemma3 12B runs, e5-small loses quality
  on Japanese.
- Lazy model load: SentenceTransformer is constructed on first
  ``retrieve`` call so import-time cost is zero. The pipeline can
  instantiate the retriever in ``--generate`` setup without paying the
  ~3-5s model load when RAG is disabled.
- e5 prefix convention: e5 expects ``"query: ..."`` and ``"passage: ..."``
  prefixes — applied transparently inside ``retrieve`` and the indexer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_DEFAULT_INDEX_PATH = _REPO / "data" / "rag_index"
_DEFAULT_MODEL = "intfloat/multilingual-e5-base"

# Bump when chunking strategy or embedding model changes so a stale
# index is detected. Must match build_rag_index.py::_CHUNKER_VERSION —
# _ensure_loaded() warns when the on-disk index sentinel disagrees.
_INDEX_VERSION = "v1"
_EXPECTED_CHUNKER_VERSION = "2026-06-15-per-example"


@dataclass
class RetrievedChunk:
    """Single retrieval result.

    Attributes:
        text: The chunk body (already stripped of any e5 ``passage:``
            prefix).
        metadata: Anything attached to the chunk at index time —
            typically ``source_file``, ``section_title``, ``date``.
        score: cos similarity in [0.0, 1.0]. Higher = closer.
    """

    text: str
    metadata: dict
    score: float


class RagRetriever:
    """Read-only retriever over the chromadb index.

    Usage::

        r = RagRetriever()
        hits = r.retrieve(
            "AI副業 ライティング 単価",
            collection="anti_patterns",
            top_k=3,
        )
        for h in hits:
            print(f"[{h.score:.2f}] {h.text[:80]}")

    The retriever is safe to construct even when the index doesn't
    exist yet — ``retrieve`` returns an empty list in that case
    (logged at WARNING) so callers don't have to special-case the
    pre-build state.
    """

    def __init__(
        self,
        index_path: Path = _DEFAULT_INDEX_PATH,
        model_name: str = _DEFAULT_MODEL,
    ) -> None:
        self._index_path = Path(index_path)
        self._model_name = model_name
        # Lazy fields.
        self._model = None
        self._client = None

    def _ensure_loaded(self) -> bool:
        """Load model + chromadb client on first use. Returns False if
        the index directory is missing (caller should treat as no-hits).
        """
        if self._client is not None:
            return True
        if not self._index_path.exists():
            logger.warning(
                "RAG index not found at %s — retrieve() will return empty. "
                "Run scripts/build_rag_index.py to create it.",
                self._index_path,
            )
            return False
        try:
            from sentence_transformers import SentenceTransformer
            import chromadb
        except ImportError as exc:
            logger.warning(
                "RAG deps not installed (%s) — retrieve() will return empty",
                exc,
            )
            return False
        try:
            self._model = SentenceTransformer(self._model_name)
            self._client = chromadb.PersistentClient(
                path=str(self._index_path),
            )
            self._warn_if_stale_index()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG retriever load failed: %s", exc)
            return False

    def _warn_if_stale_index(self) -> None:
        """Warn (once) when the on-disk index was built by a different
        chunker version than this code expects.

        Read-only: never rebuilds (the retriever must stay side-effect free
        and rebuild is expensive). The --learn pipeline rebuilds daily, so a
        loud warning is enough to catch a stale index after a chunking
        change instead of letting it masquerade as healthy (Codex #3).
        """
        sentinel = self._index_path / "chunker_version.txt"
        try:
            found = sentinel.read_text(encoding="utf-8").strip() if sentinel.exists() else None
        except OSError:
            found = None
        if found != _EXPECTED_CHUNKER_VERSION:
            logger.warning(
                "RAG index chunker version mismatch (on-disk=%r, expected=%r) "
                "— rebuild with scripts/build_rag_index.py (or run --learn) so "
                "retrieval reflects the current chunking.",
                found, _EXPECTED_CHUNKER_VERSION,
            )

    def retrieve(
        self,
        query: str,
        collection: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[RetrievedChunk]:
        """Return up to ``top_k`` chunks from ``collection`` closest to
        ``query``, filtered to those above ``score_threshold``.

        Args:
            query: Natural-language query (Japanese OK). Will be
                prefixed with ``"query: "`` for e5.
            collection: chromadb collection name.
            top_k: Max hits to return.
            score_threshold: Drop hits below this cos sim. ``0.0`` keeps
                everything; ``0.5`` is a reasonable safety floor.

        Returns:
            List of ``RetrievedChunk`` sorted high-to-low by score.
            Empty list if the index isn't built yet OR if no chunks
            meet the threshold.
        """
        if not self._ensure_loaded():
            return []
        try:
            coll = self._client.get_collection(collection)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RAG collection '%s' not found (%s)", collection, exc,
            )
            return []
        query_emb = self._model.encode(
            [f"query: {query}"], normalize_embeddings=True,
        ).tolist()
        results = coll.query(
            query_embeddings=query_emb,
            n_results=top_k,
        )
        hits: list[RetrievedChunk] = []
        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        dists = (results.get("distances") or [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            # chromadb default is squared L2 on normalized vectors;
            # convert to cos sim approximation: 1 - dist/2 for unit
            # vectors gives a [0,1] score. Floor at 0 just in case.
            score = max(0.0, 1.0 - float(dist) / 2.0)
            if score < score_threshold:
                continue
            # Strip the "passage:" prefix we attached at index time.
            text = doc.removeprefix("passage: ")
            hits.append(
                RetrievedChunk(
                    text=text,
                    metadata=dict(meta) if meta else {},
                    score=score,
                ),
            )
        return hits

    def retrieve_many(
        self,
        query: str,
        plan: Sequence[tuple[str, int]],
        score_threshold: float = 0.0,
    ) -> dict[str, list[RetrievedChunk]]:
        """Run several ``retrieve`` calls in one go.

        ``plan`` is a list of ``(collection_name, top_k)`` tuples. The
        return dict is keyed by collection name. Useful for the
        ``_load_learned_block`` replacement which wants e.g.
        ``[("anti_patterns", 3), ("successes", 3), ("hallucinations", 2)]``.
        """
        out: dict[str, list[RetrievedChunk]] = {}
        for collection, top_k in plan:
            out[collection] = self.retrieve(
                query, collection, top_k=top_k,
                score_threshold=score_threshold,
            )
        return out

    # ------------------------------------------------------------------
    # Re-ranking layer (2026-05-14 evening — Codex H#6 + Stage 2 of RAG
    # advancement). CrossEncoder re-scores (query, candidate) pairs
    # jointly so semantic-near-duplicates can be told apart from real
    # matches. The bi-encoder kNN above is recall-oriented; the
    # cross-encoder layer is precision-oriented.
    #
    # Default off. Set RAG_RERANKER=true (or pass a model name) to
    # enable. Lazy-loaded so import cost stays zero when unused.
    # ------------------------------------------------------------------

    _DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"

    def _ensure_reranker_loaded(self) -> bool:
        """Lazy-load the cross-encoder reranker. Returns False on any
        failure so callers can transparently fall back to bi-encoder hits.
        """
        if getattr(self, "_reranker", None) is not None:
            return True
        import os
        model_name = (
            os.environ.get("RAG_RERANKER_MODEL")
            or self._DEFAULT_RERANKER_MODEL
        )
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            logger.warning(
                "reranker deps missing (%s) — retrieve_with_rerank "
                "falls back to bi-encoder ranking", exc,
            )
            self._reranker = False  # sentinel: tried-and-failed
            return False
        try:
            self._reranker = CrossEncoder(model_name)
            logger.info("reranker loaded: %s", model_name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "reranker load failed (%s) — falling back to bi-encoder",
                exc,
            )
            self._reranker = False
            return False

    def retrieve_with_rerank(
        self,
        query: str,
        collection: str,
        top_k: int = 5,
        candidate_k: int = 20,
        score_threshold: float = 0.0,
        rerank_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        """Two-stage retrieval: bi-encoder kNN → cross-encoder rerank.

        Args:
            query: Natural-language query.
            collection: chromadb collection name.
            top_k: Final number of chunks to return after rerank.
            candidate_k: How many candidates to pull from kNN before
                rerank. Larger = better recall at the cost of latency.
                15-30 is the usual sweet spot for chromadb-sized indices.
            score_threshold: Floor on the initial bi-encoder cos sim.
                Same semantics as ``retrieve()``.
            rerank_threshold: Optional floor on the cross-encoder score
                (its own scale — usually 0..1 for sigmoid-normalised
                models, but raw logits otherwise). ``None`` means "no
                second floor".

        Returns:
            Up to ``top_k`` chunks sorted high-to-low by rerank score.
            ``RetrievedChunk.score`` carries the RERANK score, and the
            original bi-encoder score is stashed in ``metadata["bi_score"]``
            so callers can compare.

        Falls back to ``retrieve(top_k=top_k)`` transparently when the
        reranker model can't load (no internet, deps missing, etc.).
        """
        candidates = self.retrieve(
            query=query,
            collection=collection,
            top_k=candidate_k,
            score_threshold=score_threshold,
        )
        if not candidates:
            return []
        if not self._ensure_reranker_loaded() or not candidates:
            # Fallback: trim to top_k and return bi-encoder ranking as-is.
            return candidates[:top_k]
        try:
            pairs = [(query, c.text) for c in candidates]
            scores = self._reranker.predict(pairs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rerank predict failed (%s) — bi-encoder fallback", exc,
            )
            return candidates[:top_k]
        # Pair scores back to candidates, sort, optional threshold,
        # trim to top_k.
        ranked: list[RetrievedChunk] = []
        for cand, s in zip(candidates, scores):
            new_meta = dict(cand.metadata or {})
            new_meta["bi_score"] = round(cand.score, 4)
            ranked.append(
                RetrievedChunk(
                    text=cand.text,
                    metadata=new_meta,
                    score=float(s),
                )
            )
        ranked.sort(key=lambda r: r.score, reverse=True)
        if rerank_threshold is not None:
            ranked = [r for r in ranked if r.score >= rerank_threshold]
        return ranked[:top_k]

    def retrieve_multi_query(
        self,
        queries: Sequence[str],
        collection: str,
        top_k: int = 5,
        candidate_k_per_query: int = 10,
        score_threshold: float = 0.0,
        use_rerank: bool = True,
        rerank_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        """Multi-query expansion: run several query variants, union the
        candidate pools (dedup on identical chunk text), then rerank
        (if available) and return top_k.

        Why: a single Japanese query embedding can miss paraphrases
        ("○○大学の教授によれば" vs "○○大学の研究者は〜と指摘"). Running
        2-3 variants and merging boosts recall before precision-ranking.

        ``queries[0]`` is treated as the canonical query for rerank
        scoring (the other variants are only used to widen the candidate
        pool). Caller usually passes the original query first, then
        paraphrases / sub-questions.
        """
        if not queries:
            return []
        # Pool candidates from each query variant; dedup by chunk text.
        seen_texts: set[str] = set()
        merged: list[RetrievedChunk] = []
        for q in queries:
            for c in self.retrieve(
                query=q,
                collection=collection,
                top_k=candidate_k_per_query,
                score_threshold=score_threshold,
            ):
                if c.text in seen_texts:
                    continue
                seen_texts.add(c.text)
                merged.append(c)
        if not merged:
            return []
        if not use_rerank or not self._ensure_reranker_loaded():
            # Sort merged pool by bi-encoder score and trim.
            merged.sort(key=lambda r: r.score, reverse=True)
            return merged[:top_k]
        try:
            canonical = queries[0]
            pairs = [(canonical, c.text) for c in merged]
            scores = self._reranker.predict(pairs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "multi-query rerank failed (%s) — bi-encoder fallback", exc,
            )
            merged.sort(key=lambda r: r.score, reverse=True)
            return merged[:top_k]
        ranked: list[RetrievedChunk] = []
        for cand, s in zip(merged, scores):
            new_meta = dict(cand.metadata or {})
            new_meta["bi_score"] = round(cand.score, 4)
            ranked.append(
                RetrievedChunk(
                    text=cand.text,
                    metadata=new_meta,
                    score=float(s),
                )
            )
        ranked.sort(key=lambda r: r.score, reverse=True)
        if rerank_threshold is not None:
            ranked = [r for r in ranked if r.score >= rerank_threshold]
        return ranked[:top_k]
