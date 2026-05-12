"""Generate cover + 4 inline images for the AI sidejob 30-day roadmap article.

Inline images go to the 4 Week sections (Week 1-4) via the new
section-priority logic in chatgpt_batch_helper. Brave must be CLOSED.
"""
from __future__ import annotations

import logging
import re
import sys
import os
import time
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
logger = logging.getLogger("gen_ai_sidejob_roadmap_images")

TITLE = (
    "【2026-05実証データ版】AI副業30日ロードマップ — "
    "月¥175,634クリエイターの公開実績から逆算した月¥5万達成の最短ルート"
)
GENRE = "AI副業 / 個人マネタイズ / ChatGPT / Claude / 自動化 / 副業ロードマップ"
DRAFT = _REPO / "data" / "articles" / "_drafts" / "ai_sidejob_30day_roadmap_20260512.md"


def main() -> int:
    if not DRAFT.exists():
        logger.error("draft missing: %s", DRAFT)
        return 2
    content = DRAFT.read_text(encoding="utf-8")
    h2_count = len(re.findall(r"^##\s+", content, re.MULTILINE))
    logger.info("draft loaded: %d chars, %d H2 sections", len(content), h2_count)

    from generators.chatgpt_batch_helper import (
        chatgpt_image_batch,
        is_chatgpt_image_gen_enabled,
    )
    if not is_chatgpt_image_gen_enabled():
        logger.error("ChatGPT image gen disabled (USE_CHATGPT_IMAGES env)")
        return 3

    cover, inline = chatgpt_image_batch(
        title=TITLE,
        content=content,
        inline_count=4,
        slug_hint="ai_sidejob_30day_roadmap",
        genre_hint=GENRE,
    )

    print("\n=== RESULT ===")
    print(f"cover: {cover}")
    print("inline:")
    for i, p in enumerate(inline, 1):
        print(f"  [{i}] {p}")
    return 0 if (cover and len(inline) >= 3) else 4


if __name__ == "__main__":
    raise SystemExit(main())
