"""Inject Unsplash inline images into a live note post via edit_article.

Workaround used while the publish_article path's HTML paste flow is
still being debugged. Loads the stored article JSON for the
なおちゃんラーメン post, runs the same swap+paste edit pipeline that
test_inline_image_edit.py validated, and then verifies the live page
contains rehosted ``<img>`` elements.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

for _line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

from publishers.note_publisher import NotePublisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("inject_images_to_live_note")


TARGET_JSON = _REPO / "data" / "articles" / "note-新年初ランチ_なおちゃんラーメン_塩中華.json"
TARGET_URL = "https://note.com/note-user/n/n06546a2cc83f"


def main() -> int:
    if not TARGET_JSON.exists():
        logger.error("missing JSON: %s", TARGET_JSON)
        return 1

    data = json.loads(TARGET_JSON.read_text(encoding="utf-8"))
    title = data["title"]
    content = data["content"]

    img_md = re.findall(r"!\[[^\]]*\]\([^)]+\)", content)
    logger.info("stored markdown images: %d", len(img_md))
    for m in img_md:
        logger.info("  %s", m[:160])

    pub = NotePublisher(headless=False)
    try:
        ok = pub.edit_article(url=TARGET_URL, new_title=title, new_content=content)
    finally:
        pub.close()

    if not ok:
        logger.error("edit_article returned False")
        return 1

    logger.info("waiting 8s for note to settle...")
    time.sleep(8)

    req = Request(TARGET_URL, headers={"User-Agent": "Mozilla/5.0 inject-verify/1.0"})
    html = urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
    article_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
    body = article_match.group(1) if article_match else ""
    img_pat = re.compile(r'<img[^>]*src="([^"]+)"', re.IGNORECASE)
    imgs = img_pat.findall(body)
    rehosted = [s for s in imgs if "assets.st-note.com/production/uploads" in s and "profile" not in s]
    direct = [s for s in imgs if "images.unsplash.com" in s]
    logger.info(
        "live body imgs: total=%d, st-note rehosted (non-profile)=%d, unsplash direct=%d",
        len(imgs), len(rehosted), len(direct),
    )
    for s in rehosted[:5]:
        logger.info("  rehosted: %s", s[:120])
    if len(rehosted) + len(direct) < 1:
        logger.error("FAIL — no inline images on live page")
        return 1
    logger.info("PASS — %d inline images on live page", len(rehosted) + len(direct))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
