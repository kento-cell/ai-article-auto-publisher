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
# index is detected and rebuild is forced.
_INDEX_VERSION = "v1"


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
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG retriever load failed: %s", exc)
            return False

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
