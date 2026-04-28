"""CLI entry: run the AI Catchup pipeline once and post to Slack.

Usage:
    py scripts/run_catchup.py        # post to Slack
    py scripts/run_catchup.py --dry  # print to stdout, do not mark sent
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from dotenv import load_dotenv
load_dotenv()

from catchup.runner import run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="print digest, skip Slack")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    stats = run(dry_run=args.dry)
    print(f"DONE: {stats}")
    return 0 if stats.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
