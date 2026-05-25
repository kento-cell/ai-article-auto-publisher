"""Publish the hand-written 'K-beauty: Japan purchase routes' article to
note as a FREE (¥0) discovery article — companion/teaser piece for
upcoming paid K-beauty deep-dives (PDRN/エクソソーム, トラブル対処).

Body in ``scripts/_kbeauty_japan_purchase_guide.md`` — ~5300 chars,
9 H2 sections, second-person voice, OliveYoung Japan / @cosme TOKYO /
新大久保 / 公式オンライン / Qoo10 メガ割 the four-route map + brand-
specific recommendations + counterfeit-detection 5 axes + ステマ規制
disclosure note. Real brand names only (COSRX / Beauty of Joseon /
Anua / NATURE REPUBLIC / ETUDE), no specific SKUs or prices that would
risk hallucination. Tail link to the K-POP 4-generation paid article
(n024111feee84) as a cross-category Korean culture hook.

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
logger = logging.getLogger("publish_kbeauty_japan_guide")

TITLE = (
    "【迷ったらここ】2026年版 韓国コスメを日本で買う 4 つの場所 ― "
    "OliveYoung日本上陸後の \"正規・並行・偽物\" 整理"
)
PRICE = 0
SOURCE = "K-beauty / 韓国コスメ / OliveYoung / 新大久保 / 公式オンライン"
CONTENT_MD = _REPO / "scripts" / "_kbeauty_japan_purchase_guide.md"


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

    aid = "note-kbeauty_japan_purchase_guide"
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
        "_origin": "manual free discovery — scripts/_kbeauty_japan_purchase_guide.md",
    }
    out = _REPO / "data" / "articles" / f"{aid}.json"
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("record saved: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
