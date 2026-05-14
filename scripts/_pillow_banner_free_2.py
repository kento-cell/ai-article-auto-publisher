"""Generate Pillow banners for today's 2 free note articles
(Edge Copilot / Louis Rossmann) and edit_article to swap covers.

Same approach proven for the paid articles earlier today
(scripts/_pillow_banner_paid_2.py). ChatGPT image gen is structurally
broken (CF Turnstile + _start_new_chat bug — same MD5 across all
outputs), so Pillow is the working alternative until that path is
properly fixed.
"""
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pillow_banner_free")


# Reuse the make_banner + THEMES from the paid script
from scripts._pillow_banner_paid_2 import make_banner, THEMES  # noqa: E402


JOBS = [
    {
        "article_id": "note-Microsoft_s_Edge_Cop-d04dd4f6",
        "url": "https://note.com/note-user/n/n706c0bb4ad19",
        "new_title": "【号外】Microsoft Edge Copilot活用術：プロが教える最新AIライティング戦略と月収アップの秘訣",
        "banner": {
            "bracket": "【号外】",
            "headline": "Edge Copilot\n活用術 2026",
            "tagline": "プロが教える最新 AI ライティング戦略",
            "theme": THEMES["wasp"],  # navy + yellow — tech editorial feel
        },
    },
    {
        "article_id": "note-Louis_Rossmann_taunt-c4a7127a",
        "url": "https://note.com/note-user/n/n8eac6ab9f668",
        "new_title": "【完全保存版】3Dプリンター製造企業Bambu LabとSnapmakerの躍進：中国と香港から世界へ、革新の裏側と未来戦略",
        "banner": {
            "bracket": "【完全保存版】",
            "headline": "Bambu Lab vs\nSnapmaker 攻防",
            "tagline": "3D プリンター戦争 — Louis Rossmann が動いた日",
            "theme": THEMES["cisco"],  # navy + red — tension / news feel
        },
    },
]


def main() -> int:
    subprocess.run(
        ["taskkill", "/F", "/IM", "brave.exe"],
        check=False, capture_output=True,
    )
    time.sleep(2)

    articles_dir = _REPO / "data" / "articles"
    covers_dir = _REPO / "data" / "images" / "covers"

    # Phase 1 — generate banners + persist
    for j in JOBS:
        bp = covers_dir / f"pillow_free_{j['article_id']}_cover.png"
        make_banner(out_path=bp, **j["banner"])
        j["cover_path"] = bp
        ap = articles_dir / f"{j['article_id']}.json"
        d = json.loads(ap.read_text(encoding="utf-8"))
        d["_cover_image_before_pillow_free"] = d.get("cover_image")
        d["cover_image"] = str(bp.relative_to(_REPO))
        ap.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        logger.info("article json updated: %s", ap)

    # Phase 2 — edit_article with cover only (title + body already
    # finalized on note.com; we only swap the eyecatch).
    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[str] = []
    try:
        for j in JOBS:
            logger.info("Editing %s", j["url"])
            try:
                ok = pub.edit_article(
                    url=j["url"],
                    new_title=None,         # keep current title
                    new_content=None,        # keep current body
                    inline_image_paths=None, # keep current inlines
                    cover_image_path=str(j["cover_path"].resolve()),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("  OK: %s", j["url"])
            else:
                failed.append(j["url"])
                logger.error("  FAIL: %s", j["url"])
            time.sleep(4)
    finally:
        pub.close()

    logger.info("DONE — uploaded=%d failed=%d", succeeded, len(failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
