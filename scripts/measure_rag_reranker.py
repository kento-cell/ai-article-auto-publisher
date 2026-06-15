"""Measure whether enabling the cross-encoder reranker improves duplicate
detection on the past_articles collection — the open decision from the
2026-06-15 RAG review (RAG_RERANKER is currently false).

The duplicate guard (main._check_topic_duplication) has two paths:
  * RAG_RERANKER=false → plain bi-encoder retrieve at cos-sim >= 0.88
  * RAG_RERANKER=true  → pull 20 candidates >= 0.55, cross-encoder rerank,
                         flag at rerank score >= 0.88

The cross-encoder (BAAI/bge-reranker-base) is supposed to catch PARAPHRASED
duplicates the bi-encoder misses ("Copilot 従量課金 回避 自作" vs the stored
"従量制になったCopilotの代わりに…"). But loading it costs memory while
Gemma3 12B is resident, so it's off. This harness quantifies the trade-off:
for a labelled set of paraphrase queries (each a re-wording of a real past
article) and unrelated negatives, it reports whether each method surfaces the
known duplicate, plus reranker load/scoring latency.

    PYTHONIOENCODING=utf-8 py scripts/measure_rag_reranker.py

Reports only — changing RAG_RERANKER stays a human call (memory pressure).
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (paraphrase query, substring expected in the matched past-article title).
# Queries are re-wordings of real articles in data/articles so a working
# duplicate guard SHOULD surface the original.
PARAPHRASE_CASES: list[tuple[str, str]] = [
    ("GitHub Copilot 従量課金 回避 OpenCode Go 自作 代替プロバイダ", "OpenCode Go"),
    ("Galaxy Z Fold8 折りたたみ 画面 解像度 向上 リーク 噂", "Galaxy Z Fold8"),
    ("Anthropic Claude Fable 5 Mythos 5 新モデル 発表 まとめ 解説", "Fable 5"),
    ("シール交換 文具 携帯はさみ ピンセット一体型 レビュー 指紋", "携帯ハサミ"),
    ("ローカルLLM コーディングエージェント 自作 データ主権", "ローカルLLM"),
]

# Distinct topics with no matching past article — must NOT be flagged.
NEGATIVE_CASES: list[str] = [
    "京都 紅葉 嵐山 観光 混雑 回避 ルート",
    "子猫 餌 選び方 月齢別 カリカリ ふやかし",
    "確定申告 医療費控除 セルフメディケーション 書き方",
]

DUP_THRESHOLD = 0.88  # mirror _check_topic_duplication


def _bi_hit(retriever, query: str) -> tuple[bool, float, str]:
    hits = retriever.retrieve(query, "past_articles", top_k=3, score_threshold=0.0)
    if not hits:
        return False, 0.0, ""
    top = hits[0]
    return top.score >= DUP_THRESHOLD, top.score, top.metadata.get("section_title", "")


def _rr_hit(retriever, query: str) -> tuple[bool, float, str]:
    hits = retriever.retrieve_with_rerank(
        query, "past_articles", top_k=3, candidate_k=20,
        score_threshold=0.55, rerank_threshold=None,
    )
    if not hits:
        return False, 0.0, ""
    top = hits[0]
    return top.score >= DUP_THRESHOLD, top.score, top.metadata.get("section_title", "")


def main() -> int:
    from generators.rag_retriever import RagRetriever
    retriever = RagRetriever()

    # Warm + time the reranker load explicitly.
    t0 = time.perf_counter()
    rr_ok = retriever._ensure_reranker_loaded()
    load_s = time.perf_counter() - t0
    print(f"reranker load: {'OK' if rr_ok else 'FAILED'} ({load_s:.1f}s)\n")

    bi_recall = rr_recall = 0
    print("=== paraphrase duplicates (want: flagged True, correct title) ===")
    for q, expect in PARAPHRASE_CASES:
        bf, bs, bt = _bi_hit(retriever, q)
        t0 = time.perf_counter()
        rf, rs, rt = _rr_hit(retriever, q)
        rr_ms = (time.perf_counter() - t0) * 1000
        bi_correct = bf and expect in bt
        rr_correct = rf and expect in rt
        bi_recall += bi_correct
        rr_recall += rr_correct
        print(f"\n  q: {q[:48]}  (expect ~{expect})")
        print(f"    bi    : flag={bf} score={bs:.3f} title={bt[:34]} {'✓' if bi_correct else '✗'}")
        print(f"    rerank: flag={rf} score={rs:.3f} title={rt[:34]} {'✓' if rr_correct else '✗'} ({rr_ms:.0f}ms)")

    bi_fp = rr_fp = 0
    print("\n=== unrelated negatives (want: NOT flagged) ===")
    for q in NEGATIVE_CASES:
        bf, bs, _ = _bi_hit(retriever, q)
        rf, rs, _ = _rr_hit(retriever, q)
        bi_fp += bf
        rr_fp += rf
        print(f"  q: {q[:40]}  bi flag={bf}({bs:.2f})  rerank flag={rf}({rs:.2f})")

    n_pos, n_neg = len(PARAPHRASE_CASES), len(NEGATIVE_CASES)
    print("\n=== verdict ===")
    print(f"  paraphrase recall : bi {bi_recall}/{n_pos}   rerank {rr_recall}/{n_pos}")
    print(f"  false positives   : bi {bi_fp}/{n_neg}   rerank {rr_fp}/{n_neg}")
    delta = rr_recall - bi_recall
    if delta > 0 and rr_fp <= bi_fp:
        print(f"  → reranker catches {delta} more paraphrase dup(s) with no extra FP.")
        print(f"    Worth RAG_RERANKER=true IF the {load_s:.0f}s load + memory fits "
              f"alongside Gemma3 (human call).")
    elif delta <= 0:
        print("  → reranker does NOT improve recall here; keep RAG_RERANKER=false "
              "(saves memory).")
    else:
        print("  → reranker improves recall but adds false positives; not a clear win.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
