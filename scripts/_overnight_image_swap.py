"""Overnight orchestrator: push regenerated content + ChatGPT images to
the remaining live paid-garbage note articles, batch by batch.

Batch 1 (Power Prices / Feed Is Fake / 70% Americans / Cisco / BitLocker)
is run separately. This orchestrator handles batches 2-5 (17 articles).

Each batch is delegated to `_regen_today_note_with_chatgpt.py`, which:
  - kills Brave, generates cover+inline via ChatGPT,
  - edit_article-replaces the live note body + images.

Batches run sequentially so each finishes its edits before the next
kills Brave. A batch failure is logged and does not stop the run —
ChatGPT daily limits may degrade later batches to Unsplash fallback.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "_regen_today_note_with_chatgpt.py"

BATCHES: list[list[str]] = [
    # Batch 2
    [
        "note-Microsoft_confirms_W-abf3b1df",
        "note-Nearly_50_000_Lake_T-3264c8b9",
        "note-OpenAI_now_wants_Cha-209675b8",
        "note-The_AI_Layoff_Bill_I-1ed0597d",
        "note-Zero-day_exploit_com-ce4a843a",
    ],
    # Batch 3
    [
        "note-_Everyone_is_unhappy-f89b5415",
        "note-5_Years_and__5M_Late-f1b21453",
        "note-Cisco_s_stock_pops_1-5224bf4f",
        "note-Louis_Rossmann_taunt-c4a7127a",
        "note-Microsoft_s_Edge_Cop-d04dd4f6",
    ],
    # Batch 4
    [
        "note-PCOS_Is_Officially_R-34291c12",
        "note-Louis_Rossmann_tells-d59475f2",
        "note-Reddit_Starts_Blocki-9e0633a0",
        "note-_Cannot_be_explained-5f05d53b",
        "note-Judge_rules_DOGE_use-b4394f01",
    ],
    # Batch 5
    [
        "note-Cloudflare_lays_off_-68fac977",
        "note-GameStop_CEO_says_eB-0a33f278",
    ],
]


def main() -> int:
    start = time.time()
    print(f"=== overnight image swap — {len(BATCHES)} batches ===", flush=True)
    for i, batch in enumerate(BATCHES, start=2):
        print("\n" + "#" * 70, flush=True)
        print(f"# BATCH {i} — {len(batch)} article(s)", flush=True)
        print("#" * 70, flush=True)
        try:
            result = subprocess.run(
                [sys.executable, str(_SCRIPT), *batch],
                cwd=str(_REPO),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            print(result.stdout[-4000:], flush=True)
            if result.stderr:
                print("--- stderr tail ---", flush=True)
                print(result.stderr[-1500:], flush=True)
            print(f"# BATCH {i} exit code: {result.returncode}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"# BATCH {i} orchestrator error: {exc}", flush=True)

    elapsed = (time.time() - start) / 3600
    print(f"\n=== overnight image swap DONE — {elapsed:.1f}h ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
