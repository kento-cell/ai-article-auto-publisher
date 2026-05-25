"""Publish the hand-written 'K-beauty: ingredient-by-skin-concern guide'
article to note as a FREE (¥0) discovery article — companion to the
5-25 purchase-routes guide (n4e037aa7aeed) and teaser for upcoming
paid PDRN/exosome deep-dive.

Body in ``scripts/_kbeauty_ingredient_guide.md`` — ~6000 chars,
10 H2 sections, second-person voice. Five skin concerns
(soothing / brightening / firming / pore / dryness) × real ingredient
names (Centella, Niacinamide, Tranexamic acid, Peptide, AHA/BHA/PHA,
Hyaluronic acid, Ceramide) with real Korean brands (Anua / COSRX /
Beauty of Joseon / Skin1004 / Medi-Peel / Torriden / Dr.Jart+ etc.).
No placeholder ingredient/measurement expressions ― consistent with
2026-05-26 forbidden_phrases prompt hardening. Cross-links to the
5-25 purchase guide (Free, n4e037aa7aeed) and the K-POP 4th-gen
paid article (n024111feee84).

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
logger = logging.getLogger("publish_kbeauty_ingredient_guide")

TITLE = (
    "【保存版】韓国コスメ「成分の正解」5悩み別ガイド ― "
    "シカ・ナイアシンアミド・ペプチド・BHA・セラミドの覚え方"
)
PRICE = 0
SOURCE = (
    "K-beauty / 韓国コスメ成分 / Centella / Niacinamide / Tranexamic / "
    "Peptide / AHA/BHA/PHA / Ceramide"
)
CONTENT_MD = _REPO / "scripts" / "_kbeauty_ingredient_guide.md"


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

    aid = "note-kbeauty_ingredient_guide"
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
        "_origin": "manual free discovery — scripts/_kbeauty_ingredient_guide.md",
    }
    out = _REPO / "data" / "articles" / f"{aid}.json"
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("record saved: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
