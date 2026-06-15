"""Auto-calibrate the RAG retrieval threshold used by the generation
learned-block (main._build_rag_learned_block).

Problem (Codex review 2026-06-15, finding #1): the bi-encoder cos-sim floor
was a hand-picked 0.55. After the per-example chunking change it lets
unrelated topics retrieve generic stat chunks (e.g. a Galaxy article pulling
a K-beauty success example at 0.765), injecting irrelevant guidance into the
writer prompt.

This harness grid-searches the floor against a LABELLED set of
(query, collection, should_hit) cases and picks the threshold that best
separates topical matches from unrelated topics. The objective is Youden's J
(= recall - false_positive_rate) under a recall floor, computed per
collection so successes / anti_patterns can diverge.

The labelled set lives in this file so it is version-controlled and editable
when the corpus shifts. Re-run after any chunking / corpus change:

    PYTHONIOENCODING=utf-8 py scripts/calibrate_rag_thresholds.py
    PYTHONIOENCODING=utf-8 py scripts/calibrate_rag_thresholds.py --json

The script only REPORTS — it never edits code. Apply the recommended value
via the RAG_LEARN_THRESHOLD env / the calibrated default in main.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Labelled calibration set.
#
# POSITIVES: a query that SHOULD retrieve a topically-related example from the
# collection (the writer would benefit from seeing it).
# NEGATIVES: a query whose topic is ABSENT from the collection's examples —
# it should retrieve nothing above the floor (no irrelevant injection).
#
# Keep negatives drawn from real past note topics that are NOT in the
# top/bottom-20% example lists (家電 / コーヒー / 時計 / シェーバー …) so the
# separation we measure reflects production traffic.
# ---------------------------------------------------------------------------
POSITIVES: list[tuple[str, str]] = [
    # successes — each near a concrete success example currently in the corpus
    ("韓国コスメ スキンケア 成分 ガイド", "successes"),
    ("AI副業 ライティング 月収 始め方", "successes"),
    ("セキュリティ 個人 対策 鉄壁", "successes"),
    ("Claude 新モデル AI 発表 まとめ", "successes"),
    # anti_patterns — near the 政治/公共「そもそも解説」cluster
    ("政治家 SNS 投稿 デマ 解説", "anti_patterns"),
    ("公共機関 とは 入門 徹底解説", "anti_patterns"),
]

NEGATIVES: list[tuple[str, str]] = [
    # Topics genuinely absent from both example lists.
    ("Galaxy スマホ バッテリー 容量 6.5型", "successes"),
    ("電気ケトル ティファール 家電 比較", "successes"),
    ("コーヒー 焙煎 バリスタ 抽出", "successes"),
    ("腕時計 自動巻き 機械式 秒針", "successes"),
    ("電気シェーバー 深剃り 替刃", "successes"),
    ("Galaxy スマホ バッテリー 容量 6.5型", "anti_patterns"),
    ("電気ケトル ティファール 家電 比較", "anti_patterns"),
    ("コーヒー 焙煎 バリスタ 抽出", "anti_patterns"),
]

GRID = [round(0.50 + 0.025 * i, 3) for i in range(int((0.90 - 0.50) / 0.025) + 1)]
RECALL_FLOOR = 0.80  # don't drop below this topical recall when maximising J
TOP_K = 3  # mirror _build_rag_learned_block's top_k_each


def _hit(retriever, query: str, collection: str, threshold: float) -> float:
    """Return the best cos-sim a query gets in a collection (0.0 if none)."""
    hits = retriever.retrieve(query, collection, top_k=TOP_K, score_threshold=0.0)
    return hits[0].score if hits else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    from generators.rag_retriever import RagRetriever
    retriever = RagRetriever()

    # Pre-compute the best score each labelled query gets, once.
    collections = sorted({c for _, c in POSITIVES + NEGATIVES})
    pos_scores: dict[str, list[float]] = {c: [] for c in collections}
    neg_scores: dict[str, list[float]] = {c: [] for c in collections}
    for q, c in POSITIVES:
        pos_scores[c].append(_hit(retriever, q, c, 0.0))
    for q, c in NEGATIVES:
        neg_scores[c].append(_hit(retriever, q, c, 0.0))

    report: dict[str, dict] = {}
    for c in collections:
        rows = []
        best = None
        for th in GRID:
            pos = pos_scores[c]
            neg = neg_scores[c]
            tp = sum(1 for s in pos if s >= th)
            fp = sum(1 for s in neg if s >= th)
            recall = tp / len(pos) if pos else 0.0
            fpr = fp / len(neg) if neg else 0.0
            j = recall - fpr
            rows.append((th, recall, fpr, j))
            # Maximise Youden's J (separation), tie-break on higher recall
            # then a stricter (higher) threshold. The recall floor is
            # advisory only — for a small/generic collection no threshold
            # may reach it, and forcing recall would pick a leaky (fpr=1)
            # point. J already balances recall against false positives.
            cand = (j, recall, th)
            if best is None or cand > best[0]:
                best = (cand, th, recall, fpr, j)
        report[c] = {
            "best_threshold": best[1],
            "recall": round(best[2], 3),
            "fpr": round(best[3], 3),
            "youden_j": round(best[4], 3),
            "n_pos": len(pos_scores[c]),
            "n_neg": len(neg_scores[c]),
            "grid": [
                {"th": th, "recall": round(r, 3), "fpr": round(f, 3), "j": round(j, 3)}
                for th, r, f, j in rows
            ],
        }

    # A single learned-block threshold is simplest to wire; recommend the
    # max over collections so neither collection leaks negatives (the
    # stricter floor wins). Per-collection values are reported too.
    recommended = max(report[c]["best_threshold"] for c in collections)

    if args.json:
        print(json.dumps({"per_collection": report, "recommended_single": recommended},
                         ensure_ascii=False, indent=2))
        return 0

    print("=== RAG learned-block threshold calibration ===")
    print(f"grid {GRID[0]}..{GRID[-1]} step 0.025 | recall floor {RECALL_FLOOR} | top_k {TOP_K}\n")
    for c in collections:
        r = report[c]
        print(f"[{c}]  pos={r['n_pos']} neg={r['n_neg']}")
        print(f"  best threshold = {r['best_threshold']}  "
              f"(recall={r['recall']} fpr={r['fpr']} J={r['youden_j']})")
        # show the separation around the chosen point
        for row in r["grid"]:
            mark = " <-- pick" if row["th"] == r["best_threshold"] else ""
            if abs(row["th"] - r["best_threshold"]) <= 0.05:
                print(f"    th={row['th']:.3f}  recall={row['recall']:.2f}  "
                      f"fpr={row['fpr']:.2f}  J={row['j']:+.2f}{mark}")
        print()
    print(f"RECOMMENDED single RAG_LEARN_THRESHOLD = {recommended}")
    print("  (max across collections so neither leaks unrelated topics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
