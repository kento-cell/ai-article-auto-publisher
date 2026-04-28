"""Backtest the programmatic title-fulfillment scorer.

Reads every article in data/articles/, extracts the most aggressive
title (body's first H2 if it has bracket framing, else the JSON title),
runs the scorer, and prints distribution + worst offenders.

Usage:
    python scripts/backtest_title_fulfillment.py [--limit N] [--platform note|zenn]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Force UTF-8 stdout on Windows (cp932 default chokes on em-dash and
# many Japanese punctuation marks).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace",
    )

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generators import title_fulfillment_scorer as tfs  # noqa: E402


_BRACKET_RE = re.compile(r"[【\[]")
_FIRST_H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _resolve_title(article: dict) -> str:
    """Pick the most marketing-flavored title.

    The pipeline sometimes stores an English source title in the JSON
    while the body opens with a Japanese marketing H2. The latter is
    what the reader actually sees, so prefer it when:
    1. The JSON title is mostly ASCII (legacy English source title), OR
    2. The body H2 has bracket framing / numeric promise.
    """
    body = str(article.get("content") or "")
    json_title = str(article.get("title") or "").strip()
    h2_match = _FIRST_H2_RE.search(body)
    h2_title = h2_match.group(1).strip() if h2_match else ""
    if not h2_title:
        return json_title

    # JSON title is mostly ASCII → use Japanese H2 instead.
    ascii_ratio = (
        sum(1 for c in json_title if ord(c) < 128) / len(json_title)
        if json_title else 1.0
    )
    if ascii_ratio > 0.7 and h2_title:
        return h2_title

    if _BRACKET_RE.search(h2_title) or re.search(
        r"\d+選|\d+個|\d+ツール", h2_title,
    ):
        return h2_title
    return json_title or h2_title


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--platform", choices=("note", "zenn"), default=None,
    )
    parser.add_argument(
        "--show-c", action="store_true",
        help="Print full details of every C-graded article",
    )
    args = parser.parse_args()

    articles_dir = ROOT / "data" / "articles"
    files = sorted(articles_dir.glob("*.json"))
    if args.platform:
        files = [f for f in files if f.name.startswith(f"{args.platform}-")]
    if args.limit:
        files = files[: args.limit]

    grade_counter: Counter[str] = Counter()
    promise_type_counter: Counter[str] = Counter()
    unfulfilled_type_counter: Counter[str] = Counter()
    c_examples: list[dict] = []
    a_examples: list[dict] = []
    skipped = 0

    for f in files:
        try:
            article = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            skipped += 1
            continue
        title = _resolve_title(article)
        body = str(article.get("content") or "")
        if not title or not body:
            skipped += 1
            continue
        result = tfs.score(title, body)
        grade_counter[result["grade"]] += 1
        for p in result["promises"]:
            promise_type_counter[p["type"]] += 1
        for u in result["unfulfilled"]:
            unfulfilled_type_counter[u["type"]] += 1
        if result["grade"] == "C":
            c_examples.append({
                "file": f.name, "title": title, **result,
            })
        elif result["grade"] == "A" and len(result["promises"]) >= 3:
            a_examples.append({
                "file": f.name, "title": title, **result,
            })

    total = sum(grade_counter.values())
    print(f"\n=== Backtest results ({total} articles, skipped {skipped}) ===\n")
    for grade in ("A", "B", "C"):
        n = grade_counter.get(grade, 0)
        pct = (n / total * 100) if total else 0
        print(f"  Grade {grade}: {n:4d} ({pct:5.1f}%)")

    print("\n--- Promise type distribution ---")
    for ptype, n in promise_type_counter.most_common():
        unful = unfulfilled_type_counter.get(ptype, 0)
        rate = (unful / n * 100) if n else 0
        print(f"  {ptype:32s} promises={n:4d} unfulfilled={unful:4d} ({rate:5.1f}%)")

    if c_examples:
        print(f"\n--- Worst offenders (showing {min(10, len(c_examples))} of {len(c_examples)}) ---")
        for ex in c_examples[:10]:
            print(f"\n  [{ex['file']}]")
            print(f"  TITLE: {ex['title'][:90]}")
            for u in ex["unfulfilled"][:3]:
                print(f"    - {u.get('detail', u)}")
            if args.show_c:
                print(f"  PROMISES: {ex['promises']}")

    if a_examples and total < 30:
        print("\n--- High-fulfillment examples ---")
        for ex in a_examples[:5]:
            print(f"  [{ex['file']}] {ex['title'][:80]}")
            print(f"    fulfilled: {len(ex['promises'])} promises")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
