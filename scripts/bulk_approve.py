"""One-shot utility: promote every ⏳承認待ち row to ✅承認.

Guards (added 2026-04-22 after the メッツ / 李在明 hallucinations
leaked through an indiscriminate bulk-approve pass):

1. Skip rows whose ``overall_grade`` is ``C`` — they are only on the
   sheet because a subjective metric (usually title_fulfillment) went
   C AFTER the regen evaluation, which previously passed the outer
   ``_generate_single_article`` branch and still landed on the sheet.
2. Skip rows whose title contains a banned "〇〇氏の{SNS}投稿" hallucination
   pattern — even if the scorer was lenient, titles that name a person
   combined with a social-media post are almost always fabricated and
   should never auto-approve.

Both guards can be bypassed with ``--force`` when the operator has
reviewed the row manually.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from utils.sheets_manager import SheetsManager  # noqa: E402


# Keep in sync with config/settings.yaml:evidence.forbidden_phrases —
# this is the auto-approve guard, not the primary scorer. The scorer
# is already the authoritative ban; this subset catches the small
# number of rows that sneak past the scorer via the regen path.
# Only invitation-era / small-userbase SNS where "~氏が投稿した" claims
# are nearly always fabricated. X / Instagram / Facebook allow
# verification of posts by checking the post URL, so they are outside
# the deny list — the article's own factual content guard (forbidden
# phrases in settings.yaml) is the right place to keep catching those.
_SNS_HALLUCINATION_PATTERNS = [
    re.compile(r"氏の\s*(?:Bluesky|Threads|Mastodon)\s*投稿"),
    re.compile(r"さんの\s*(?:Bluesky|Threads|Mastodon)\s*投稿"),
    re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿が話題"),
    re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿を徹底"),
    re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿から徹底"),
    re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿から読み解"),
]


def _is_banned_title(title: str) -> str | None:
    """Return a short reason when the title matches a deny pattern,
    else ``None``. Used as a secondary guard only."""
    for pat in _SNS_HALLUCINATION_PATTERNS:
        m = pat.search(title)
        if m:
            return f"SNS hallucination pattern: {m.group(0)}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", action="store_true",
        help="bypass the grade/title guards (operator-vetted only)",
    )
    args = parser.parse_args()

    sheets = SheetsManager()
    pending = sheets.get_pending_articles()
    print(f"承認待ち: {len(pending)}件")

    approved = 0
    skipped: list[tuple[str, str]] = []
    for p in pending:
        aid = p.get("article_id", "")
        title = (p.get("title") or "")[:80]
        grade = str(p.get("overall_grade", "")).strip().upper()
        if not aid:
            continue

        if not args.force:
            if grade == "C":
                skipped.append((title, f"overall_grade=C (rejected by scorer)"))
                continue
            reason = _is_banned_title(title)
            if reason:
                skipped.append((title, reason))
                continue

        sheets.update_status(aid, "✅承認")
        approved += 1
        print(f"  → 承認: {title}")

    if skipped:
        print()
        print(f"スキップ: {len(skipped)}件 (--force で強制承認可)")
        for title, reason in skipped:
            print(f"  × {title}  — {reason}")

    print()
    print(f"承認: {approved}件 / スキップ: {len(skipped)}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
