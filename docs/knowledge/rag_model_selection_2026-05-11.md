# RAG embedding model benchmark (2026-05-11)

Corpus: 277 chunks across 4 collections.
Eval set: 22 hand-crafted golden queries.
Hardware: same machine as production (single GPU/CPU run).

## Results (sorted by Recall@5, then MRR)

| Rank | Model | Recall@5 | MRR@10 | Embed (s) | Load (s) | Query (ms) |
|------|-------|----------|--------|-----------|----------|------------|
| 1 | intfloat/multilingual-e5-base | 100.0% | 0.977 | 32.96 | 6.16 | 33.59 |
| 2 | BAAI/bge-m3 | 100.0% | 0.955 | 134.9 | 28.5 | 115.76 |
| 3 | intfloat/multilingual-e5-large | 100.0% | 0.932 | 122.28 | 25.15 | 114.93 |
| 4 | cl-nagoya/ruri-large | — | — | — | — | ERROR: Unrecognized processing class in cl-nagoya/ruri-large. Can't instantiate a proce |

## Notes

- Recall@5 = fraction of queries where the correct chunk appears in the top-5 retrieved hits.
- MRR@10 = mean reciprocal rank, computed across the top-10 retrieved hits.
- Eval set covers all 4 collections (hallucinations, anti_patterns, successes, past_articles) to avoid bias toward any one knowledge type.
- All models tested with e5-style prefixing (`query: ...` and `passage: ...`) for fairness.

## Decision

**Selected: `intfloat/multilingual-e5-base`** — top Recall@5 + MRR with acceptable load/embed cost on the production hardware.
