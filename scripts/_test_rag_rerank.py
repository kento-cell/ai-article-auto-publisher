"""Smoke test the new reranker layer on the live chromadb index."""
import sys
sys.path.insert(0, 'E:/ai-article-auto-publisher')
from generators.rag_retriever import RagRetriever

r = RagRetriever()

print("=== Test 1: hallucinations collection (BYU 型架空引用) ===")
hits = r.retrieve_with_rerank(
    query='○○大学の専門家によれば、AI が今後ますます重要になると指摘されている',
    collection='hallucinations',
    top_k=3,
    candidate_k=10,
    score_threshold=0.55,
)
print(f"hits: {len(hits)}")
for h in hits:
    bi = h.metadata.get('bi_score') if h.metadata else None
    title = h.metadata.get('section_title', '') if h.metadata else ''
    print(f"  rerank={h.score:.3f} bi={bi} | {title[:80]}")

print()
print("=== Test 2: multi-query expansion ===")
hits2 = r.retrieve_multi_query(
    queries=[
        '架空大学の専門家引用',
        '○○大学の研究者によれば',
        'BYU 教授 Utah State University',
    ],
    collection='hallucinations',
    top_k=3,
    candidate_k_per_query=5,
    score_threshold=0.55,
    use_rerank=True,
)
print(f"hits: {len(hits2)}")
for h in hits2:
    bi = h.metadata.get('bi_score') if h.metadata else None
    title = h.metadata.get('section_title', '') if h.metadata else ''
    print(f"  rerank={h.score:.3f} bi={bi} | {title[:80]}")

print()
print("=== Test 3: ops_incidents (今日の事案検索) ===")
hits3 = r.retrieve_with_rerank(
    query='ChatGPT 画像生成が同じ note ロゴを返す MD5 同一',
    collection='ops_incidents',
    top_k=3,
    candidate_k=8,
    score_threshold=0.55,
)
print(f"hits: {len(hits3)}")
for h in hits3:
    bi = h.metadata.get('bi_score') if h.metadata else None
    title = h.metadata.get('section_title', '') if h.metadata else ''
    print(f"  rerank={h.score:.3f} bi={bi} | {title[:80]}")
