"""Publish the hand-written RAG-freelance technical book to note as a
paid (JPY 1,980) article.

This is a one-off premium piece, NOT a pipeline-generated article — the
body is curated in ``scripts/_rag_freelance_book.md`` (Opus-authored,
source-grounded: market figures are cited public data, the RAG section
describes this repo's real production pipeline). It therefore bypasses
the collect→score→Sheets flow and calls ``main._publish_note`` directly.

``_publish_note`` handles hashtag generation, ChatGPT cover+inline image
generation (Brave must be stopped first), and the note Selenium publish.
ChatGPT chat sessions are soft-deleted per-image inside
``ChatGPTImageGenerator.generate_batch``.

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
logger = logging.getLogger("publish_rag_book")

TITLE = "月100万円のRAGエンジニアになる技術書 ― 単価の実データと、本番RAGパイプライン全公開"
PRICE = 1980
SOURCE = "AI / RAG / フリーランス / 技術書"
CONTENT_MD = _REPO / "scripts" / "_rag_freelance_book.md"


def main() -> int:
    # ChatGPT image gen uses launch_persistent_context — Brave must be
    # fully stopped or the profile lock causes a 90s hang → Unsplash.
    subprocess.run(
        ["taskkill", "/F", "/IM", "brave.exe"],
        check=False, capture_output=True,
    )
    time.sleep(2)

    content = CONTENT_MD.read_text(encoding="utf-8").strip()
    logger.info("article: %s chars, title=%r", len(content), TITLE)

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
    aid = "note-rag_freelance_book"
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
        "_origin": "manual premium technical book — scripts/_rag_freelance_book.md",
    }
    out = _REPO / "data" / "articles" / f"{aid}.json"
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("record saved: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
