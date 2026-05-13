"""Publish all approved articles with the first N note articles forced free.

Wraps ``main.publish_approved`` and monkey-patches
``NotePublisher.determine_price`` so that the first N note publishes
return ``0`` (free), and subsequent ones fall back to the normal
grade × evidence pricing.

Usage:
    py scripts/_publish_free_first.py --free-first 3
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--free-first", type=int, default=0,
        help="number of leading note publishes to force ¥0 (free)",
    )
    args = p.parse_args()

    from publishers.note_publisher import NotePublisher  # noqa: E402
    from publishers.gmail_notifier import GmailNotifier  # noqa: E402
    from publishers.slack_notifier import SlackNotifier  # noqa: E402
    from utils.feedback_recorder import FeedbackRecorder  # noqa: E402
    from utils.sheets_manager import SheetsManager  # noqa: E402
    from main import load_config, publish_approved  # noqa: E402

    counter = {"remaining": max(0, int(args.free_first))}
    original = NotePublisher.determine_price

    def patched(overall_grade: str, evidence_level: str) -> int:
        if counter["remaining"] > 0:
            counter["remaining"] -= 1
            print(
                f"[free-first] forcing ¥0 — "
                f"{counter['remaining']} free slot(s) left after this",
                flush=True,
            )
            return 0
        return original(overall_grade, evidence_level)

    NotePublisher.determine_price = staticmethod(patched)  # type: ignore[assignment]

    config = load_config()
    sheets = SheetsManager()
    slack = SlackNotifier()
    gmail = GmailNotifier()
    feedback = FeedbackRecorder()

    print(
        f"[free-first] starting publish — first {args.free_first} note "
        f"article(s) will be free", flush=True,
    )
    results = publish_approved(sheets, config, slack, gmail, feedback)
    print(f"[free-first] done — {results}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
