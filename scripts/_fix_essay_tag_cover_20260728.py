"""One-shot: add the contest hashtag + swap the cover on the SDGs essay
(n35ce8c653833).

Why Playwright here: claude-in-chrome froze 3x on contest-UI clicks.
Tag input via Playwright is proven (4/5 tags landed at publish; only
the FIRST tag was dropped — timing race on field init, so we type it
with explicit waits). The contest's official entry requirement is the
hashtag itself, so the banner-join step is not required.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fix_essay_0728")

_REPO = Path(__file__).resolve().parent.parent
NOTE_ID = "n35ce8c653833"
COVER = _REPO / "data" / "images" / "covers" / "sdgs_essay_quiet_cover.png"
TAG = "未来のためにできること"


def main() -> int:
    from publishers.note_publisher import NotePublisher

    pub = NotePublisher()
    try:
        pub._ensure_started()
        page = pub._page
        assert page is not None
        pub._assert_logged_in()

        # 1. Edit page: swap the eyecatch first.
        page.goto(f"https://editor.note.com/notes/{NOTE_ID}/edit/",
                  wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(4000)
        ok = pub._set_eyecatch_on_current_page(str(COVER), force_replace=True)
        logger.info("eyecatch swap: %s", ok)
        if not ok:
            return 1
        # Wait for the upload to finish (https src, same poll as edit_article).
        import time as _t
        deadline = _t.time() + 30
        while _t.time() < deadline:
            try:
                ready = page.evaluate(
                    "() => { const i = document.querySelector('img[alt=\"eyecatch\"]');"
                    " return !!(i && i.src && i.src.startsWith('https://')); }"
                )
            except Exception:
                ready = False
            if ready:
                break
            page.wait_for_timeout(500)

        # 2. Proceed to publish settings.
        for sel in ("button:has-text('公開に進む')", "button:has-text('更新')"):
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    btn.click(timeout=5000)
                    break
            except Exception:
                continue
        page.wait_for_timeout(4000)
        pub._dismiss_personal_info_modal()

        # 3. Add the contest tag with deliberate waits (the publish-time
        #    race dropped the first tag; here the field is long settled).
        tag_input = None
        for sel in ("input[placeholder*='ハッシュタグ']",
                    "input[placeholder*='タグ']"):
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=8000)
                tag_input = loc
                break
            except Exception:
                continue
        if tag_input is None:
            logger.error("タグ入力欄が見つかりません")
            return 1
        tag_input.click()
        page.wait_for_timeout(800)
        tag_input.type(TAG, delay=60)
        page.wait_for_timeout(1500)   # let the suggestion list settle
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        # Verify the chip exists before saving.
        chip_ok = page.locator(f"text=#{TAG}").first.is_visible(timeout=4000)
        logger.info("tag chip visible: %s", chip_ok)

        # 4. 更新する
        saved = False
        for sel in ("button:has-text('更新する')",
                    "button:has-text('公開する'):not(:has-text('予約'))"):
            try:
                btns = page.locator(sel).all()
                for b in reversed(btns):
                    if b.is_visible(timeout=1000):
                        b.scroll_into_view_if_needed(timeout=3000)
                        b.click(timeout=5000)
                        saved = True
                        break
                if saved:
                    break
            except Exception:
                continue
        logger.info("update clicked: %s", saved)
        page.wait_for_timeout(5000)
        pub._dismiss_popups()
        return 0 if (saved and chip_ok) else 1
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
