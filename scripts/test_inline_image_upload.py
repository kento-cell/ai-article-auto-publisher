"""One-shot: verify inline image upload to note CDN works end-to-end.

Loads an existing stored note article, extracts its local stock image
paths using the same logic ``main._publish_note`` now applies, then
calls ``NotePublisher.edit_article`` with ``inline_image_paths`` set so
note uploads the local files to ``assets.st-note.com/production/uploads``.

After the edit settles, fetches the live page HTML and counts how many
``<img>`` tags point to assets.st-note.com (= note-rehosted) vs external
hotlinks — that ratio is the pass/fail signal.
"""

from __future__ import annotations

import json
import logging
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

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO / ".env")

from publishers.note_publisher import NotePublisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_inline")

TARGET_JSON = _REPO / "data" / "articles" / "note-妻夫木聡-e8910f6e.json"
TARGET_URL = "https://note.com/note-user/n/nae88baf8a537"


def _extract_local_images(content: str) -> list[str]:
    """Mirror of main._publish_note's inline-image extractor."""
    hits: list[str] = []
    for m in re.finditer(r"!\[[^\]]*\]\((data/images/[^\s)]+)", content):
        p = _REPO / m.group(1)
        if p.exists() and p.stat().st_size > 0:
            hits.append(str(p.resolve()))
    return hits[:4]


def main() -> int:
    if not TARGET_JSON.exists():
        logger.error("missing JSON: %s", TARGET_JSON)
        return 1

    data = json.loads(TARGET_JSON.read_text(encoding="utf-8"))
    title = data["title"]
    content = data["content"]

    images = _extract_local_images(content)
    logger.info("inline image paths: %d", len(images))
    for p in images:
        logger.info("  %s (%d bytes)", p, Path(p).stat().st_size)

    if not images:
        logger.error("no local stock images found — cannot test CDN upload")
        return 1

    pub = NotePublisher(headless=False)
    try:
        ok = pub.edit_article(
            url=TARGET_URL,
            new_title=title,
            new_content=content,
            inline_image_paths=images,
        )
    finally:
        pub.close()

    if not ok:
        logger.error("edit_article returned False")
        return 1

    logger.info("waiting 12s for note.com to settle...")
    time.sleep(12)

    # Verify the live page has re-hosted images
    req = Request(TARGET_URL, headers={"User-Agent": "Mozilla/5.0 test-inline/1.0"})
    html = urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
    article_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
    body = article_match.group(1) if article_match else ""
    img_pat = re.compile(r'<img[^>]*src="([^"]+)"', re.IGNORECASE)
    imgs = img_pat.findall(body)

    rehosted = [s for s in imgs if "assets.st-note.com/production/uploads" in s and "profile" not in s]
    direct = [s for s in imgs if "images.unsplash.com" in s]

    logger.info(
        "live body: total=%d, rehosted=%d, unsplash_direct=%d",
        len(imgs), len(rehosted), len(direct),
    )
    for s in rehosted[:5]:
        logger.info("  rehosted: %s", s[:120])

    if len(rehosted) < 1:
        logger.error("FAIL — 0 images rehosted to note CDN")
        return 1
    logger.info("PASS — %d images rehosted to note CDN", len(rehosted))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
