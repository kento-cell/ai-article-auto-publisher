"""End-to-end sanity test for note.com embedded-link editing.

Runs a single-article edit against a known published post and then
fetches the live page to verify that the intended anchors (`<a>`
elements with the expected ``href``) actually exist. Prints a PASS or
FAIL summary so the caller can decide whether to run the broader
repair script.

Usage:
    venv/Scripts/python.exe scripts/test_note_link_embed.py
"""

from __future__ import annotations

import io
import logging
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from publishers.note_publisher import NotePublisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_note_link_embed")


TARGET_URL = "https://note.com/note-user/n/n08c2bf51d0b7"  # 風神
TITLE = "【テスト】下北沢の和食居酒屋「風神」— 埋め込みリンクの動作確認"

# Minimal body that exercises two embedded links and one plain paragraph.
BODY = """## 埋め込みリンクのテスト記事

この記事は埋め込みリンクの挙動を検証するための一時コンテンツです。

下北沢の和食居酒屋「風神」については[公式サイト](https://fujin.gorp.jp/)を参照してください。

また、元のBlueskyポストは[こちら](https://bsky.app/profile/shiromamu.bsky.social/post/3ltmijuugy22s)から見られます。

## 参考リンク

- [公式サイト](https://fujin.gorp.jp/)
- [Blueskyで見る](https://bsky.app/profile/shiromamu.bsky.social/post/3ltmijuugy22s)
"""


EXPECTED_HREFS = [
    "https://fujin.gorp.jp/",
    "https://bsky.app/profile/shiromamu.bsky.social/post/3ltmijuugy22s",
]


def _fetch_live_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 note-link-test/1.0"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _count_anchors_for(html: str, href: str) -> int:
    pattern = re.compile(
        r"<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>([^<]*)</a>",
        re.IGNORECASE,
    )
    return sum(1 for m in pattern.finditer(html) if m.group(1) == href)


def main() -> int:
    pub = NotePublisher(headless=False)
    try:
        logger.info("Editing %s", TARGET_URL)
        ok = pub.edit_article(
            url=TARGET_URL,
            new_title=TITLE,
            new_content=BODY,
        )
        if not ok:
            logger.error("edit_article returned False")
            return 1
    finally:
        pub.close()

    logger.info("Waiting 8s for note.com to publish the update...")
    time.sleep(8)

    logger.info("Fetching live URL to verify anchors...")
    try:
        html = _fetch_live_html(TARGET_URL)
    except Exception as exc:
        logger.error("Failed to fetch live URL: %s", exc)
        return 1

    missing: list[str] = []
    for href in EXPECTED_HREFS:
        count = _count_anchors_for(html, href)
        status = "OK" if count >= 1 else "MISSING"
        logger.info("  [%s] %s (found=%d)", status, href, count)
        if count < 1:
            missing.append(href)

    if missing:
        logger.error("FAIL — missing embedded anchors: %s", missing)
        return 1
    logger.info("PASS — all expected anchors are present on the live page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
