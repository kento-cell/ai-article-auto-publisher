"""Standalone inline-image generation test for the akabane gourmet draft.

Bypasses the publish flow — calls chatgpt_image_batch directly so we can
inspect whether per-section distillation correctly maps each shop's
section to its signature dish (うなぎ / もつ焼き / 立ち飲み etc.).

Brave must be CLOSED before running (launch_persistent_context mode).
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_akabane_inline_images")


TITLE = "赤羽せんべろ4軒 — 戦後闇市から続く立ち飲み・もつ焼き・うなぎの聖地"
DRAFT = _REPO / "data" / "articles" / "_drafts" / "akabane_gourmet_20260511.md"


def main() -> int:
    if not DRAFT.exists():
        logger.error("draft not found: %s", DRAFT)
        return 2

    content = DRAFT.read_text(encoding="utf-8")
    logger.info("loaded %d chars, H2 sections: %d", len(content),
                len(re.findall(r"^##\s+", content, re.MULTILINE)))

    from generators.chatgpt_batch_helper import (
        chatgpt_image_batch,
        is_chatgpt_image_gen_enabled,
    )
    if not is_chatgpt_image_gen_enabled():
        logger.error("ChatGPT image gen is not enabled (USE_CHATGPT_IMAGES env)")
        return 3

    cover, inline_paths = chatgpt_image_batch(
        title=TITLE,
        content=content,
        inline_count=4,
        slug_hint="akabane_inline_test",
        genre_hint="日本のローカル酒場 / 居酒屋 / もつ焼き / うなぎ / 立ち飲み",
    )

    print("\n=== RESULT ===")
    print(f"cover: {cover}")
    print("inline:")
    for i, p in enumerate(inline_paths, 1):
        print(f"  [{i}] {p}")
    return 0 if (cover or inline_paths) else 4


if __name__ == "__main__":
    raise SystemExit(main())
