"""Re-run regen_5_28 for the 2 standard-route articles that the first
pass failed on (monkey-patch staticmethod-descriptor restore bug —
fixed in _regen_5_28_note_images.py). The 2 poster-route articles
already succeeded in the first pass so we skip them here."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the fixed regen script and override its TARGETS to just the
# two that need redoing. Leaving _regen_5_28_note_images.py's TARGETS
# intact means the original script remains a faithful record of what
# the first pass attempted.
from scripts import _regen_5_28_note_images as base  # noqa: E402

base.TARGETS = [
    ("note-1週間で持ち物を1-2割減らせる_丁寧な-1406264b", "standard"),
    ("note-Tech_CEOs_are_appare-e403776c", "standard"),
]

if __name__ == "__main__":
    raise SystemExit(base.main())
