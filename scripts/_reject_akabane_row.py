"""One-shot: mark the row whose article_id starts with 'note-赤羽'
as ❌却下 so bulk_approve won't pick it up. User said
「赤羽名店はもういいよ」on 2026-05-14."""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
_ENV = _REPO / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from utils.sheets_manager import SheetsManager  # noqa: E402

sm = SheetsManager()
ws = sm._sheet
rows = ws.get_all_values()
for i, r in enumerate(rows, start=1):
    if i < 2:
        continue
    aid = r[0] if r else ""
    if aid.startswith("note-赤羽"):
        print(f"row {i}: aid={aid[:40]}")
        sm.update_status(aid, "❌却下")  # ❌却下
        print(f"  marked rejected")
