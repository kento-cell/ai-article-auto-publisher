"""Fix the なおちゃんラーメン post: clean title, add inline ramen image.

Uses :meth:`NotePublisher.edit_article` with the new
``inline_image_paths`` parameter. Workflow:

1. Download a real ramen photo from Unsplash to a local file.
2. Strip the existing ``![alt](path "url")`` image markdown from
   the stored content (those lines never embed anyway because
   note's schema filters external image URLs out of HTML paste).
3. Call ``edit_article`` with the cleaned title, the cleaned body,
   and the ramen image as ``inline_image_paths``. The publisher
   handles title update, HTML body paste, then ProseMirror
   paste-image upload at the top of the body, then save.
4. Verify the live page contains a non-cover, non-profile inline
   image rehosted under assets.st-note.com.
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
logger = logging.getLogger("fix_ramen_post")


TARGET_JSON = _REPO / "data" / "articles" / "note-新年初ランチ_なおちゃんラーメン_塩中華.json"
TARGET_URL = "https://note.com/kento_kanazawa/n/n06546a2cc83f"
NEW_TITLE = "【現地レポ】下北沢「なおちゃんラーメン」塩中華そばがBlueskyで話題に"
DOWNLOAD_PATH = _REPO / "data" / "images" / "stock" / "naochan_ramen_inline.jpg"


def _download_unsplash(query: str) -> Path:
    sourcer = ImageSourcer()
    imgs = sourcer.find_images(query, count=1)
    if not imgs:
        raise RuntimeError(f"no Unsplash result for {query!r}")
    url = imgs[0].get("url") or imgs[0].get("download_url")
    if not url:
        raise RuntimeError("no usable image url")
    DOWNLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 ramen-fetch/1.0"})
    DOWNLOAD_PATH.write_bytes(urlopen(req, timeout=30).read())
    logger.info("downloaded %s (%d bytes)", DOWNLOAD_PATH, DOWNLOAD_PATH.stat().st_size)
    return DOWNLOAD_PATH


def _strip_image_markdown(content: str) -> str:
    return re.sub(
        r"^!\[[^\]]*\]\([^)]+\)\s*$\n?",
        "",
        content,
        flags=re.MULTILINE,
    )


def main() -> int:
    if not TARGET_JSON.exists():
        logger.error("missing JSON: %s", TARGET_JSON)
        return 1

    image_path = _download_unsplash("ramen noodle bowl")

    data = json.loads(TARGET_JSON.read_text(encoding="utf-8"))
    cleaned_content = _strip_image_markdown(data["content"])
    data["title"] = NEW_TITLE
    data["content"] = cleaned_content
    TARGET_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("stored JSON updated; title=%s", NEW_TITLE)

    pub = NotePublisher(headless=False)
    try:
        ok = pub.edit_article(
            url=TARGET_URL,
            new_title=NEW_TITLE,
            new_content=cleaned_content,
            inline_image_paths=[str(image_path)],
        )
    finally:
        pub.close()

    if not ok:
        logger.error("edit_article returned False")
        return 1

    logger.info("waiting 10s for note to settle...")
    time.sleep(10)

    html = urlopen(
        Request(TARGET_URL, headers={"User-Agent": "Mozilla/5.0 verify/1.0"}),
        timeout=30,
    ).read().decode("utf-8", "replace")
    art_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
    body_html_live = art_match.group(1) if art_match else ""
    imgs = re.findall(r'<img[^>]*src="([^"]+)"', body_html_live)
    # note inline body images live under assets.st-note.com/img/...
    # while covers go to /production/uploads/images/.../rectangle_large_type_2_...
    # and avatars go to /production/uploads/images/.../profile_...
    inline = [
        s for s in imgs
        if "assets.st-note.com/img/" in s
    ]

    title_meta = re.search(
        r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html
    )
    logger.info("live og:title: %s", title_meta.group(1) if title_meta else "?")
    logger.info(
        "live imgs total=%d, inline (non-cover/profile)=%d",
        len(imgs), len(inline),
    )
    for s in inline[:5]:
        logger.info("  inline: %s", s[:140])

    if len(inline) >= 1:
        logger.info("PASS — inline image present on live page")
        return 0
    logger.error("FAIL — no inline image found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
