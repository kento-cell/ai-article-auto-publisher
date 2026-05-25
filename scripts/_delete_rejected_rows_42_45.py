"""One-shot: delete rejected rows 42-45 from Sheets to clear the 24h
recently-rejected cooldown for k_culture/slow_living topics that fail-
closed before the grounding-gate fix landed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from utils.sheets_manager import SheetsManager  # noqa: E402


def main() -> None:
    sm = SheetsManager()
    sm._authorize()
    rej = sm._open_rejected_worksheet()
    if rej is None:
        print("rejected sheet unavailable")
        return

    # delete in reverse order to keep row numbers stable
    for row in (45, 44, 43, 42):
        try:
            rej.delete_rows(row)
            print(f"deleted rejected row {row}")
        except Exception as e:
            print(f"row {row} delete failed: {e}")


if __name__ == "__main__":
    main()
