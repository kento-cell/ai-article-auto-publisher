"""One-shot publisher for the 9-engineering article on Zenn.

Reads ``data/articles/zenn-ai-engineering-9-disciplines.json`` and
calls ``main._publish_zenn`` with cap-detection / scrap fallback intact.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("publish_9eng_zenn")

import main  # noqa: E402

JSON_PATH = _REPO / "data" / "articles" / "zenn-ai-engineering-9-disciplines.json"


def main_cli() -> int:
    if not JSON_PATH.exists():
        logger.error("missing JSON: %s", JSON_PATH)
        return 2
    stored = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    title = stored["title"]
    content = stored["content"]
    article_id = stored["article_id"]

    logger.info("publishing zenn article: %s", title[:80])
    try:
        url = main._publish_zenn(article_id, title, content, stored)
    except Exception as exc:
        logger.exception("publish crashed: %s", exc)
        return 4

    if not url:
        logger.error("publish returned empty url (likely cap or scrap fallback)")
        return 5

    logger.info("published: %s", url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
