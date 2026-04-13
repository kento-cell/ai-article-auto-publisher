"""End-to-end test: insert real Unsplash images into an existing note post.

Picks the 青空カフェ部 article (cafe theme), fetches two cafe photos
from Unsplash, splices them at natural H2 boundaries in the stored
content, and pushes the result via NotePublisher.edit_article. Then
fetches the live page and verifies that the images materialised as
``<img>`` elements rehosted on note's CDN.

Run once:
    venv/Scripts/python.exe scripts/test_inline_image_edit.py
"""

from __future__ import annotations

import io
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

# Load .env so ImageSourcer can authenticate against Unsplash.
for _line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

from generators.image_sourcer import ImageSourcer  # noqa: E402
from publishers.note_publisher import NotePublisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_inline_image_edit")


TARGET_JSON = _REPO / "data" / "articles" / "note-_青空カフェ部__青空ごはん部__外食班.json"
TARGET_URL = "https://note.com/note-user/n/n3111501b8657"


def _build_image_markdown(img: dict, slug: str, idx: int) -> str:
    alt = (img.get("alt_text") or "").replace("[", "(").replace("]", ")")
    if not alt:
        alt = "cafe scene"
    url = (img.get("url") or img.get("download_url") or "").strip()
    # Use a local-looking path so _strip_local_images recognises the
    # pattern; the title attribute carries the real CDN URL.
    return f'![{alt}](data/images/stock/{slug}_{idx}.jpg "{url}")'


def _inject_images_into_content(content: str, blocks: list[str]) -> str:
    """Insert each block right after a different H2 heading."""
    lines = content.splitlines()
    out: list[str] = []
    h2_count = 0
    inserted = 0
    for line in lines:
        out.append(line)
        if line.startswith("## ") and inserted < len(blocks):
            h2_count += 1
            # Skip the very first H2 (title-ish) and inject after each
            # subsequent one until we run out of blocks.
            if h2_count >= 2:
                out.append("")
                out.append(blocks[inserted])
                inserted += 1
    if inserted < len(blocks):
        # If there were not enough H2s to host all images, append the
        # leftovers at the end.
        out.append("")
        out.extend(blocks[inserted:])
    return "\n".join(out)


def _verify_images(url: str) -> int:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 image-verify/1.0"})
    html = urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
    direct = len(re.findall(r"images\.unsplash\.com", html))
    rehosted = len(
        re.findall(r"assets\.st-note\.com/production/uploads/images/[^\"']+", html)
    )
    logger.info("  unsplash direct=%d rehosted=%d", direct, rehosted)
    return direct + rehosted


def main() -> int:
    if not TARGET_JSON.exists():
        logger.error("missing target JSON: %s", TARGET_JSON)
        return 1

    sourcer = ImageSourcer()
    images = sourcer.find_images("cafe interior", count=2)
    if len(images) < 2:
        logger.error("expected 2 images, got %d", len(images))
        return 1
    logger.info("fetched %d images from Unsplash", len(images))

    blocks = [
        _build_image_markdown(images[0], "aozora_test", 0),
        _build_image_markdown(images[1], "aozora_test", 1),
    ]
    for b in blocks:
        logger.info("  block: %s", b[:120])

    data = json.loads(TARGET_JSON.read_text(encoding="utf-8"))
    title = data["title"]
    content = data["content"]
    new_content = _inject_images_into_content(content, blocks)
    if new_content == content:
        logger.error("injection did not change content")
        return 1
    data["content"] = new_content
    TARGET_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("stored JSON updated (%d → %d chars)", len(content), len(new_content))

    pub = NotePublisher(headless=False)
    try:
        ok = pub.edit_article(url=TARGET_URL, new_title=title, new_content=new_content)
    finally:
        pub.close()

    if not ok:
        logger.error("edit_article returned False")
        return 1

    logger.info("waiting 8s for note to settle...")
    time.sleep(8)

    found = _verify_images(TARGET_URL)
    if found < 2:
        logger.error("FAIL — expected ≥2 inline images, found %d", found)
        return 1
    logger.info("PASS — %d image references on the live page", found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
