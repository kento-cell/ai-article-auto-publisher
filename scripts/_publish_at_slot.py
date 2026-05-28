"""Slot-aligned publish trigger for the note 初速の法則 (initial-velocity
algorithm boost). note's recommendation algorithm pushes a post into
おすすめ based on reaction concentration in the first 1-2 hours after
publish. Posting at peak reader-traffic slots multiplies first-hour
reach 2-4x.

Peak slots (per [atelier jun 2025 analysis](https://note.com/fancy_snipe9439/n/nead06c21d9d4)):
  - 火 19-22 JST
  - 金 16-19 JST (17:00 最強)
  - 土 10-12 JST
  - 日 11-14 JST

Without note Premium (= no native scheduled-publish), this script:
  1. Validates that NOW is inside a peak slot
  2. If yes, calls scripts/_publish_free_first.py with passed args
  3. If no, prints the next slot ETA and exits non-zero

Usage:
  # Manual hit-at-slot:
  py scripts/_publish_at_slot.py
  py scripts/_publish_at_slot.py --free-first 999

  # Force publish even outside slot (skip the check):
  py scripts/_publish_at_slot.py --force

  # See when the next slot is without publishing:
  py scripts/_publish_at_slot.py --next

Suggested workflow:
  - Generate the night before (`py main.py --generate`)
  - bulk_approve at any time (`py scripts/_bulk_approve_sheet.py`)
  - Have Windows Task Scheduler or a manual reminder fire this script
    at the peak slot
"""
from __future__ import annotations

import argparse
import datetime as _dt
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent

# Each slot: (weekday 0=Mon-6=Sun, start_hour, end_hour) in JST.
SLOTS = [
    (1, 19, 22),  # Tue 19-22
    (4, 16, 19),  # Fri 16-19 (17:00 peak)
    (5, 10, 12),  # Sat 10-12
    (6, 11, 14),  # Sun 11-14
]
JST = _dt.timezone(_dt.timedelta(hours=9))


def _now_jst() -> _dt.datetime:
    return _dt.datetime.now(JST)


def _in_any_slot(now: _dt.datetime) -> tuple[int, int, int] | None:
    """Return (weekday, start, end) of the current slot, or None."""
    wd = now.weekday()
    hr = now.hour
    for (sw, ss, se) in SLOTS:
        if wd == sw and ss <= hr < se:
            return (sw, ss, se)
    return None


def _next_slot(now: _dt.datetime) -> _dt.datetime:
    """Return the next slot start time (JST)."""
    # Search up to 8 days ahead (covers all possible weekdays).
    for days in range(0, 8):
        cand_date = now.date() + _dt.timedelta(days=days)
        cand_wd = cand_date.weekday()
        for (sw, ss, _se) in SLOTS:
            if cand_wd != sw:
                continue
            cand = _dt.datetime.combine(
                cand_date, _dt.time(hour=ss), tzinfo=JST,
            )
            if cand > now:
                return cand
    # Shouldn't happen, but fallback.
    return now + _dt.timedelta(days=7)


def _format_slot_label(wd: int, start: int, end: int) -> str:
    days = ["月", "火", "水", "木", "金", "土", "日"]
    return f"{days[wd]} {start:02d}:00-{end:02d}:00 JST"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--free-first", type=int, default=999,
                    help="note 最初 N 本を ¥0 強制 (デフォルト 999 = 全 note free)")
    ap.add_argument("--force", action="store_true",
                    help="slot 外でも publish 実行 (緊急時のみ)")
    ap.add_argument("--next", action="store_true",
                    help="次の slot ETA を表示して exit (publish しない)")
    args = ap.parse_args()

    now = _now_jst()
    if args.next:
        nxt = _next_slot(now)
        delta = nxt - now
        hrs = delta.total_seconds() / 3600
        print(f"now:  {now.strftime('%Y-%m-%d %H:%M JST (%a)')}")
        print(f"next slot: {nxt.strftime('%Y-%m-%d %H:%M JST (%a)')} "
              f"(in {hrs:.1f}h)")
        all_labels = ", ".join(
            _format_slot_label(sw, ss, se) for (sw, ss, se) in SLOTS
        )
        print(f"all slots: {all_labels}")
        return 0

    slot = _in_any_slot(now)
    if slot is None and not args.force:
        nxt = _next_slot(now)
        delta = nxt - now
        hrs = delta.total_seconds() / 3600
        print(f"[slot-publish] 現在 {now.strftime('%a %H:%M JST')} は "
              f"peak slot 外 (-> 初速の法則 boost 効かず)")
        print(f"[slot-publish] 次の slot: {nxt.strftime('%a %H:%M JST')} "
              f"(あと {hrs:.1f}h)")
        print(f"[slot-publish] 強制実行は --force、 ETA 確認は --next")
        return 2

    if slot:
        print(f"[slot-publish] in slot: {_format_slot_label(*slot)} "
              f"now={now.strftime('%H:%M')} — publish 実行")
    else:
        print(f"[slot-publish] --force 指定 — slot 外で publish 実行")

    cmd = [
        sys.executable,
        str(_REPO / "scripts" / "_publish_free_first.py"),
        "--free-first", str(args.free_first),
    ]
    return subprocess.call(cmd, cwd=str(_REPO))


if __name__ == "__main__":
    raise SystemExit(main())
