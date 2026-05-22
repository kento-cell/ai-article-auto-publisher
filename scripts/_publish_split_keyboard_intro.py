"""Publish the hand-written "split keyboard intro" article to note as a
FREE (¥0) article — companion/teaser piece to the paid desk-setup article
(scripts/_publish_ai_engineer_desk.py, ¥500).

Body in ``scripts/_split_keyboard_intro.md`` — 10 H2 / ~5200 chars,
second-person voice, anatomical justification of split keyboards, 7
real products (ZSA Moonlander, MoErgo Glove80, Kinesis Advantage360 Pro,
Microsoft Sculpt Ergonomic, Logitech ERGO K860, Keychron Q11/Q14), the
Oryx/QMK/ZMK layering ecosystem, three "things you lose" honest caveats,
and a tail link to the paid desk-setup article.

Bypasses collect→score→Sheets and calls ``main._publish_note`` directly.
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
logger = logging.getLogger("publish_split_kb_intro")

TITLE = (
    "【先に手首を救え】分割キーボード入門 ― "
    "Moonlander / Glove80 / Kinesis、 AIエンジニアの最初の1台"
)
PRICE = 0
SOURCE = "ガジェット / 分割キーボード / メカニカルキーボード / AI エンジニア / 健康"
CONTENT_MD = _REPO / "scripts" / "_split_keyboard_intro.md"


def main() -> int:
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

    aid = "note-split_keyboard_intro"
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
        "_origin": "manual free teaser — scripts/_split_keyboard_intro.md",
    }
    out = _REPO / "data" / "articles" / f"{aid}.json"
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("record saved: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
