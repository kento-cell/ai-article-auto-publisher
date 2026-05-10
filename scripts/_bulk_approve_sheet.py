"""Bulk-approve every '⏳承認待ち' row in the dashboard sheet.

Uses gspread's batch_update so that we issue ONE Sheets API request
instead of N (avoiding the per-write rate limit at scale). Rejected
('❌却下') and already-published rows are left untouched.

Idempotent: re-running it just re-asserts ✅承認 on rows already
flipped.
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
    HEADER_ROW,
    _COL_INDEX,
)

PENDING = STATUS_CHOICES[0]   # ⏳承認待ち
APPROVED = STATUS_CHOICES[1]  # ✅承認


def main() -> int:
    sm = SheetsManager()
    if sm._sheet is None:
        print("Sheets not configured (missing creds or sheet id)")
        return 2

    rows = sm._sheet.get_all_values()
    if len(rows) <= 1:
        print("sheet has no data rows")
        return 0

    status_col = _COL_INDEX["status"]  # 1-based
    col_letter = chr(ord("A") + status_col - 1)

    updates: list[dict] = []
    flipped: list[str] = []
    for i, row in enumerate(rows[1:], start=2):  # row 2 onwards
        if len(row) < status_col:
            continue
        current = row[status_col - 1]
        if current != PENDING:
            continue
        title = row[_COL_INDEX["title"] - 1] if len(row) >= _COL_INDEX["title"] else ""
        updates.append(
            {
                "range": f"{col_letter}{i}",
                "values": [[APPROVED]],
            }
        )
        flipped.append(f"  row {i}: {title[:60]}")

    if not updates:
        print("nothing to approve — no ⏳承認待ち rows")
        return 0

    print(f"flipping {len(updates)} row(s) to ✅承認:")
    for line in flipped:
        print(line)

    sm._sheet.batch_update(updates, value_input_option="USER_ENTERED")
    print(f"DONE — {len(updates)} rows now ✅承認")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
