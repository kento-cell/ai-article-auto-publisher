"""Bulk-approve only note '⏳承認待ち' rows. Zenn rows are skipped.

2026-05-15: ユーザー指示「zenn は無視、note のみ集中」のために用意。
通常の `_bulk_approve_sheet.py` は全 platform 一括 approve するが、
今日は zenn cap 中で publish したくないので platform=note のみ。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from utils.sheets_manager import (  # noqa: E402
    SheetsManager,
    STATUS_CHOICES,
    _COL_INDEX,
)

PENDING = STATUS_CHOICES[0]   # ⏳承認待ち
APPROVED = STATUS_CHOICES[1]  # ✅承認
TARGET_PLATFORM = "note"


def main() -> int:
    sm = SheetsManager()
    if sm._sheet is None:
        print("Sheets not configured (missing creds or sheet id)")
        return 2

    rows = sm._sheet.get_all_values()
    if len(rows) <= 1:
        print("sheet has no data rows")
        return 0

    status_col = _COL_INDEX["status"]
    platform_col = _COL_INDEX["platform"]
    col_letter = chr(ord("A") + status_col - 1)

    updates: list[dict] = []
    flipped: list[str] = []
    skipped_other: list[str] = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) < max(status_col, platform_col):
            continue
        current = row[status_col - 1]
        if current != PENDING:
            continue
        platform = (row[platform_col - 1] or "").strip().lower()
        title = row[_COL_INDEX["title"] - 1] if len(row) >= _COL_INDEX["title"] else ""
        if platform != TARGET_PLATFORM:
            skipped_other.append(f"  row {i} [{platform}]: {title[:50]}")
            continue
        updates.append({
            "range": f"{col_letter}{i}",
            "values": [[APPROVED]],
        })
        flipped.append(f"  row {i}: {title[:60]}")

    if skipped_other:
        print(f"skipped {len(skipped_other)} non-note pending row(s):")
        for line in skipped_other:
            print(line)

    if not updates:
        print("nothing to approve — no note ⏳承認待ち rows")
        return 0

    print(f"flipping {len(updates)} note row(s) to ✅承認:")
    for line in flipped:
        print(line)

    sm._sheet.batch_update(updates, value_input_option="USER_ENTERED")
    print(f"DONE — {len(updates)} note rows now ✅承認")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
