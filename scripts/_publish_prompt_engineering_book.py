"""Publish the hand-written prompt-engineering technical book to note
as a paid (JPY 1,980) article.

Companion piece to the RAG-freelance book (5-18). The body is curated
in ``scripts/_prompt_engineering_book.md`` (Opus-authored, source-grounded:
API prices cite Anthropic / OpenAI / Google public pricing pages as of
2026-05; the 18 templates and 8 incident-style war stories come from
this repo's actual operational history). It bypasses the collect→score→
Sheets flow and calls ``main._publish_note`` directly.

``_publish_note`` handles hashtag generation, ChatGPT cover+inline image
generation, and the note Selenium publish. ChatGPT chat sessions are
soft-deleted per-image inside ``ChatGPTImageGenerator.generate_batch``.

A minimal article record is written to ``data/articles/`` afterwards so
the post is verifiable (og:image) and portable across sessions.
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
logger = logging.getLogger("publish_prompt_eng_book")

TITLE = (
    "プロンプトエンジニアリング実務本 2026 ― "
    "Claude 4.7 / GPT-5.4 / Gemini 2.5 のクセを全部書いた、"
    "案件で使う型と月コスト70%削った技術"
)
PRICE = 1980
SOURCE = "AI / プロンプトエンジニアリング / フリーランス / 技術書"
CONTENT_MD = _REPO / "scripts" / "_prompt_engineering_book.md"


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

    # Persist a minimal article record for verification + portability.
    aid = "note-prompt_engineering_book"
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
        "_origin": "manual premium technical book — scripts/_prompt_engineering_book.md",
    }
    out = _REPO / "data" / "articles" / f"{aid}.json"
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("record saved: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
