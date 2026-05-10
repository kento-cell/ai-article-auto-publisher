"""Single-shot pollinations.ai smoke test.

Verifies that the new fallback path can actually fetch + save an
image before we restart the production publish job.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from generators.chatgpt_batch_helper import _pollinations_image_batch  # noqa: E402

out_dir = _REPO / "data" / "images" / "covers"
out_dir.mkdir(parents=True, exist_ok=True)

ts = time.strftime("%Y%m%d_%H%M%S")
prompts = [
    "futuristic developer coding with multiple AI agents floating around, "
    "cyberpunk neon style, blue and purple lighting, tech illustration",
    "Two AI assistants debating over CLAUDE.md and AGENTS.md files, "
    "studio ghibli style, warm lighting",
]
out_paths = [
    out_dir / f"_pollinations_smoke_{ts}_cover.png",
    out_dir / f"_pollinations_smoke_{ts}_inline.png",
]
print(f"requesting {len(prompts)} images via Pollinations…")
results = _pollinations_image_batch(prompts, out_paths)
ok = sum(1 for r in results if r and r.exists())
print(f"results: {ok}/{len(prompts)} succeeded")
for r in results:
    if r and r.exists():
        print(f"  OK: {r.name} ({r.stat().st_size} bytes)")
    else:
        print(f"  FAIL: {r}")
sys.exit(0 if ok > 0 else 1)
