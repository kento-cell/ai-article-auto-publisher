"""Publish the free Shinjuku hidden-gem izakaya note article.

Free (price=0) note article. The body lives in
scripts/_shinjuku_izakaya_article.md — curated from gourmet-media
research, with no fabricated shop names / addresses / menus and
chain-signal shops excluded.

ChatGPT cover + inline images are generated via the CDP-attached
Brave (CHATGPT_CDP_PORT), so Brave does NOT need to be closed —
unlike the older publish scripts, this one ensures a CDP Brave is up
instead of killing it.
"""
from __future__ import annotations

import json
import logging
import os
import socket
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
logger = logging.getLogger("publish_shinjuku_izakaya")

TITLE = "新宿、チェーンしか思い浮かばない夜に。穴場居酒屋5軒"
PRICE = 0  # free article (user-confirmed)
SOURCE = "グルメ / 居酒屋 / 新宿 / 夜の酒場"
CONTENT_MD = _REPO / "scripts" / "_shinjuku_izakaya_article.md"


def _ensure_cdp_brave() -> None:
    """Make sure a CDP-debug Brave is up; launch via the .bat if not."""
    port = int(os.environ.get("CHATGPT_CDP_PORT", "9222"))

    def _open() -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    if _open():
        logger.info("CDP Brave already up on port %d", port)
        return
    logger.info("CDP Brave not up — running launch_brave_cdp.bat")
    subprocess.run(
        ["cmd", "/c", str(_REPO / "scripts" / "launch_brave_cdp.bat")],
        capture_output=True, timeout=30,
    )
    for _ in range(20):
        if _open():
            logger.info("CDP Brave came up")
            return
        time.sleep(2)
    logger.warning("CDP Brave did not come up — generator may fall back")


def main() -> int:
    _ensure_cdp_brave()

    content = CONTENT_MD.read_text(encoding="utf-8").strip()
    logger.info("article: %d chars, title=%r", len(content), TITLE)

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

    aid = "note-shinjuku_izakaya"
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
        "_origin": "manual free gourmet article — scripts/_shinjuku_izakaya_article.md",
    }
    out = _REPO / "data" / "articles" / f"{aid}.json"
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("record saved: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
