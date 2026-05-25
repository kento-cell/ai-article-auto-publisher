"""One-shot: print rejection reasons for k_beauty rows in rejected sheet."""
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

    values = rej.get_all_values()
    print(f"total rows: {len(values)}")
    print(f"header: {values[0]}")
    for i in range(1, len(values)):
        title = (values[i][0] if len(values[i]) > 0 else "")[:80]
        if "K-beauty" in title or "韓国コスメ" in title or "PDRN" in title:
            print(f"\nrow {i+1}:")
            for j, h in enumerate(values[0]):
                cell = values[i][j] if j < len(values[i]) else ""
                if len(cell) > 300:
                    cell = cell[:300] + "..."
                print(f"  {h}: {cell}")


if __name__ == "__main__":
    main()
