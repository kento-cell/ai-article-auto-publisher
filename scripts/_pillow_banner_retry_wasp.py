"""Retry Wasp paid note edit_article (eyecatch swap race failed once)."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
os.environ.setdefault("CHATGPT_VISION_EVAL", "0")
os.environ.setdefault("USE_CHATGPT_IMAGES", "0")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("retry_wasp")

AID = "note-5_Years_and__5M_Late-f1b21453"
URL = "https://note.com/note-user/n/nc46a11cd674e"
NEW_TITLE = "【完全暴露】Wasp 創業者が $5M と5年を溶かして気づいた「DSL を作るのは堀じゃなかった」— Y Combinator 出身チームの正直すぎる反省録"


def main() -> int:
    subprocess.run(["taskkill", "/F", "/IM", "brave.exe"], check=False, capture_output=True)
    time.sleep(2)

    ap = _REPO / "data" / "articles" / f"{AID}.json"
    d = json.loads(ap.read_text(encoding="utf-8"))
    body = d["content"]
    lines = body.splitlines()
    if lines and lines[0].startswith("## ") and NEW_TITLE[:10] in lines[0]:
        body = "\n".join(lines[1:]).lstrip()
    body = re.sub(
        r"\n?!\[[^\]]*\]\(data/images/[^)\s]+(?:\s+\"[^\"]*\")?\)\n?",
        "\n", body,
    )
    cover = (_REPO / d["cover_image"]).resolve()
    assert cover.exists(), f"missing cover: {cover}"

    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    try:
        for attempt in (1, 2, 3):
            logger.info("=== attempt %d ===", attempt)
            try:
                ok = pub.edit_article(
                    url=URL,
                    new_title=NEW_TITLE,
                    new_content=body,
                    inline_image_paths=None,
                    cover_image_path=str(cover),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                logger.info("OK on attempt %d: %s", attempt, URL)
                return 0
            logger.warning("attempt %d failed, retrying in 5s", attempt)
            time.sleep(5)
    finally:
        pub.close()
    logger.error("all attempts exhausted")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
