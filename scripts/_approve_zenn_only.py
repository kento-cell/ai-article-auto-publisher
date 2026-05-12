"""Approve ⏳承認待ち rows where platform == 'zenn' only.

Used for the 2026-05-12 batch: user asked for zenn publish specifically,
leaving any note-bound rows untouched for manual review.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from utils.sheets_manager import SheetsManager  # noqa: E402


def main() -> int:
    sheets = SheetsManager()
    pending = sheets.get_pending_articles()
    print(f"⏳承認待ち: {len(pending)} 件")

    approved = 0
    skipped: list[tuple[str, str]] = []
    for p in pending:
        aid = p.get("article_id", "")
        title = (p.get("title") or "")[:60]
        platform = str(p.get("platform", "")).strip().lower()
        grade = str(p.get("overall_grade", "")).strip().upper()

        if not aid:
            continue
        if platform != "zenn":
            skipped.append((title, f"platform={platform!r} (zenn 限定)"))
            continue
        if grade == "C":
            skipped.append((title, "overall_grade=C (rejected by scorer)"))
            continue

        sheets.update_status(aid, "✅承認")
        approved += 1
        print(f"  → 承認: [{platform}] {title}")

    if skipped:
        print()
        print(f"スキップ: {len(skipped)} 件")
        for title, reason in skipped:
            print(f"  × {title}  — {reason}")

    print()
    print(f"承認: {approved} 件 / スキップ: {len(skipped)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
