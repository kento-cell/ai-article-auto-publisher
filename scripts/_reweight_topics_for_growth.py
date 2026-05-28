"""Rebalance data/knowledge_topics.json rotation weights for the
2026-05-28 growth pivot (K-beauty 主軸, 14→500 follower plan).

Pre-state (audited 2026-05-28):
  ai_sidejob       14 topics × 10.91 = 152.7  (53%)
  ai_literacy      13 topics ×  8.52 = 110.8  (38%)
  physical_ai       7 topics ×  0.89 =   6.2  ( 2%)
  k_beauty          6 topics ×  1.02 =   6.1  ( 2%)
  k_culture         3 topics ×  1.03 =   3.1  ( 1%)
  slow_living       3 topics ×  1.13 =   3.4  ( 1%)
  self_improvement  3 topics ×  0.90 =   2.7  ( 1%)
  hidden_gourmet    3 topics ×  0.60 =   1.8  ( 1%)
  coffee_barista    2 topics ×  0.85 =   1.7  ( 1%)

Post-state target (per docs/strategy/2026-05-28_growth_plan.md):
  K-beauty/韓国 主軸     70%   (k_beauty + k_culture)
  AI × 副業    副軸     20%   (ai_sidejob = real-money, ai_literacy = bridge)
  その他                10%   (residual self-improvement)
  捨てる                  0%   (physical_ai / hidden_gourmet / slow_living /
                                coffee_barista — internal data shows all
                                flop, 赤羽系 memory + lane sprawl 排除)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
TOPICS_PATH = _REPO / "data" / "knowledge_topics.json"

# (category, new per-topic weight)
NEW_WEIGHTS = {
    "k_beauty": 11.0,           # 6 × 11 = 66 (48.9%)
    "k_culture": 11.0,          # 3 × 11 = 33 (24.4%)
    "ai_sidejob": 2.0,          # 14 × 2 = 28 (20.7%)  ← real-money
    "ai_literacy": 0.5,         # 13 × 0.5 = 6.5 (4.8%)  ← bridge
    "self_improvement": 0.5,    # 3 × 0.5 = 1.5 (1.1%)
    "physical_ai": 0.0,         # zeroed — out of lane
    "hidden_gourmet": 0.0,      # zeroed — 赤羽飽き memory + lane sprawl
    "slow_living": 0.0,         # zeroed — internal data shows flop
    "coffee_barista": 0.0,      # zeroed — lane sprawl
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry-run)")
    args = ap.parse_args()

    data = json.loads(TOPICS_PATH.read_text(encoding="utf-8"))
    topics = data.get("topics", [])

    pre_totals: dict[str, float] = Counter()
    pre_counts: dict[str, int] = Counter()
    for t in topics:
        cat = t.get("category", "?")
        pre_totals[cat] += float(t.get("rotation_weight", 0))
        pre_counts[cat] += 1

    print("=== BEFORE ===")
    total_pre = sum(pre_totals.values())
    for cat in sorted(pre_counts, key=lambda c: -pre_totals[c]):
        pct = 100 * pre_totals[cat] / total_pre if total_pre else 0
        print(f"  {cat:20s} {pre_counts[cat]:3d} topics × "
              f"avg {pre_totals[cat]/max(1,pre_counts[cat]):5.2f} = "
              f"{pre_totals[cat]:6.1f}  ({pct:5.1f}%)")
    print(f"  TOTAL: {total_pre:.1f}\n")

    changed = 0
    for t in topics:
        cat = t.get("category", "?")
        if cat not in NEW_WEIGHTS:
            continue
        old_w = float(t.get("rotation_weight", 0))
        new_w = NEW_WEIGHTS[cat]
        if abs(old_w - new_w) < 1e-9:
            continue
        t["rotation_weight"] = new_w
        if new_w == 0.0:
            # Match existing convention: zero-weighted topics also get
            # disabled_reason so the sampler skips them entirely (see
            # collectors/knowledge_topics_collector.py 2026-05-14 fix).
            t["disabled_reason"] = "2026-05-28 growth pivot — out of lane"
        else:
            # Clear disabled_reason if we're re-enabling
            t.pop("disabled_reason", None)
        changed += 1

    post_totals: dict[str, float] = Counter()
    post_counts: dict[str, int] = Counter()
    for t in topics:
        cat = t.get("category", "?")
        post_totals[cat] += float(t.get("rotation_weight", 0))
        post_counts[cat] += 1

    print("=== AFTER ===")
    total_post = sum(post_totals.values())
    for cat in sorted(post_counts, key=lambda c: -post_totals[c]):
        pct = 100 * post_totals[cat] / total_post if total_post else 0
        avg = post_totals[cat] / max(1, post_counts[cat])
        print(f"  {cat:20s} {post_counts[cat]:3d} topics × "
              f"avg {avg:5.2f} = {post_totals[cat]:6.1f}  ({pct:5.1f}%)")
    print(f"  TOTAL: {total_post:.1f}")
    print(f"\nchanged: {changed} topic(s)")

    # Lane summary
    kb_korea = post_totals["k_beauty"] + post_totals["k_culture"]
    ai_real = post_totals["ai_sidejob"]
    ai_bridge = post_totals["ai_literacy"]
    other = post_totals["self_improvement"]
    kbpct = 100 * kb_korea / total_post if total_post else 0
    aipct = 100 * (ai_real + ai_bridge) / total_post if total_post else 0
    otpct = 100 * other / total_post if total_post else 0
    print(f"\nLane summary: K-beauty/韓国 {kbpct:.1f}% / "
          f"AI {aipct:.1f}% / その他 {otpct:.1f}%")

    if args.apply:
        TOPICS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nAPPLIED — wrote {TOPICS_PATH.relative_to(_REPO)}")
    else:
        print("\nDRY-RUN — pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
