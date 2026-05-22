"""Publish the hand-written "AI engineer ideal desk setup" article to
note as a paid (JPY 500) article.

Companion to the prompt-engineering / RAG-freelance books. Body is in
``scripts/_ai_engineer_desk_setup.md`` — 16 real products across 11
gadget categories (chair, desk, monitor, split keyboard, mouse, mic,
headphones, lighting, dock, storage, software), three budget tiers,
and an Amazon-search link table with affiliate tag ``YOUR_AMAZON_TAG``.
No fictional products; every brand/model is a real shipping product
verified at write time (2026-05).

Bypasses the collect→score→Sheets flow and calls ``main._publish_note``
directly, which handles ChatGPT cover+inline image generation, hashtag
generation, and note Selenium publish. ChatGPT chat sessions are
soft-deleted per-image inside ``ChatGPTImageGenerator.generate_batch``.

A minimal article record is written to ``data/articles/`` for portability
and og:image verification.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("publish_ai_engineer_desk")

TITLE = (
    "【2026年版】生成AIエンジニアの理想デスク回り16製品 ― "
    "椅子・分割キーボード・マイク・モニター、毎日12時間座る人間が揃えるべき全部"
)
PRICE = 500
# genre_hint steers ChatGPT image batch toward photorealistic
# product/setting photography rather than infographic/illustration.
SOURCE = "ガジェット / デスク回り / AI エンジニア / ホームオフィス / リモートワーク"
CONTENT_MD = _REPO / "scripts" / "_ai_engineer_desk_setup.md"


def main() -> int:
    # ChatGPT image gen uses launch_persistent_context — Brave must be
    # fully stopped or the profile lock causes a 90s hang → Unsplash.
    # If CDP is configured (CHATGPT_CDP_PORT in .env), the generator
    # attaches over CDP and Brave can stay open.
    if not os.environ.get("CHATGPT_CDP_PORT"):
        subprocess.run(
            ["taskkill", "/F", "/IM", "brave.exe"],
            check=False, capture_output=True,
        )
        time.sleep(2)

    content = CONTENT_MD.read_text(encoding="utf-8").strip()
    logger.info("article: %s chars, title=%r", len(content), TITLE[:60])

    import main as pipeline

    config = pipeline.load_config()

    url = pipeline._publish_note(
        title=TITLE,
        content=content,
        config=config,
        source=SOURCE,
        price=PRICE,
    )

    if not url:
        logger.error("publish FAILED — no URL returned")
        return 1

    logger.info("PUBLISHED: %s (price=¥%d)", url, PRICE)

    aid = "note-ai_engineer_desk_setup"
    record = {
        "title": TITLE,
        "content": content,
        "platform": "note",
        "source": SOURCE,
        "article_id": aid,
        "price": PRICE,
        "published_url": url,
        "published_at": datetime.now().isoformat(timespec="seconds"),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "_origin": "manual gadget review — scripts/_ai_engineer_desk_setup.md",
    }
    out = _REPO / "data" / "articles" / f"{aid}.json"
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("record saved: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
