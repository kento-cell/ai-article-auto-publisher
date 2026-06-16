"""One-shot: add contest hashtags to the just-published #AIで遊ぼう entry.

The 2026-06-17 00:07 cron-fired publish (n444be2daa2ef) shipped without
tags — the Selenium tag flow silently skipped (_input_tags is called
after _open_publish_settings, but the publish-settings screen layout has
drifted and no tag-input was found). For contest eligibility this is
critical: #AIで遊ぼう is the entry tag.

This script reuses NotePublisher's Playwright session to:
  1. open the editor for the article
  2. drive it to the publish-settings screen via the same
     _open_publish_settings flow
  3. call _input_tags directly with the contest tag set
  4. click 「更新する」to save
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for ln in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("add_tags_contest")

from publishers.note_publisher import NotePublisher  # noqa: E402

NOTE_KEY = "n444be2daa2ef"
# Round 2: previous run persisted only #AIフェスティバル. Re-add the missing
# critical contest tag + supporting tags. Put #AIで遊ぼう FIRST so it gets
# the longest commit window before 「更新する」 is pressed.
TAGS = [
    "AIで遊ぼう",  # contest-required, must persist
    "AI活用",
    "Claude",
    "ChatGPT",
    "生成AI",
]


def main() -> int:
    pub = NotePublisher(headless=False)
    try:
        pub._ensure_started()  # noqa: SLF001
        page = pub._page  # noqa: SLF001
        assert page is not None
        pub._assert_logged_in()  # noqa: SLF001

        # Note ID is the part after /n/. note's editor takes the same
        # 12-hex id as the public URL.
        edit_url = f"https://editor.note.com/notes/{NOTE_KEY}/edit/"
        logger.info("opening editor: %s", edit_url)
        page.goto(edit_url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(4000)
        if "login" in page.url or "enter" in page.url:
            logger.error("not logged in to note.com")
            return 1

        # Wait for the editor to mount
        try:
            page.wait_for_selector(".ProseMirror", timeout=20_000)
        except Exception:
            logger.warning("editor mount slow — continuing anyway")

        # Step 1: explicitly click the "公開に進む" button to leave the
        # body editor and enter the publish-settings panel.
        forward_clicked = False
        for sel in [
            "button:has-text('公開に進む')",
            "button:has-text('公開設定')",
            "button:has-text('更新する')",
        ]:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=4_000)
                loc.click(timeout=3_000)
                logger.info("forward clicked: %s", sel)
                forward_clicked = True
                break
            except Exception:
                continue
        if not forward_clicked:
            logger.error("could not click 公開に進む — aborting")
            return 2

        # Wait for the publish-settings page to load.
        page.wait_for_timeout(4000)
        logger.info("on URL after forward: %s", page.url)

        # Step 2: find the tag input on the publish-settings page and add
        # all contest tags. note's tag input expects: click, type, Enter.
        tag_selectors = [
            "input[placeholder*='ハッシュタグ']",
            "input[placeholder*='タグ']",
            "[data-testid='tag-input']",
            "input[type='text'][placeholder*='#']",
        ]
        tag_input = None
        for sel in tag_selectors:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=6_000)
                tag_input = loc
                logger.info("tag input found via: %s", sel)
                break
            except Exception:
                continue
        if tag_input is None:
            logger.error("tag input NOT found — dumping visible inputs")
            try:
                inputs = page.locator("input").all()
                for i, inp in enumerate(inputs[:20]):
                    try:
                        ph = inp.get_attribute("placeholder") or ""
                        nm = inp.get_attribute("name") or ""
                        if ph or nm:
                            logger.info("  input[%d]: placeholder=%r name=%r", i, ph, nm)
                    except Exception:
                        pass
            except Exception:
                pass
            return 3

        for tag in TAGS[:5]:
            try:
                tag_input.click()
                page.wait_for_timeout(400)
                tag_input.type(tag, delay=30)
                page.wait_for_timeout(800)
                page.keyboard.press("Enter")
                page.wait_for_timeout(1500)  # longer wait for Vue state to commit
                logger.info("tag added: %s", tag)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tag '%s' failed: %s", tag, exc)

        page.wait_for_timeout(4000)  # extra dwell before save click

        # Step 3: click the final 更新する / 公開する button on the
        # publish-settings panel to persist the change.
        save_clicked = False
        for sel in [
            "button:has-text('更新する')",
            "button:has-text('公開する')",
            "button:has-text('公開')",
        ]:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=4_000)
                loc.click(timeout=3_000)
                logger.info("save clicked: %s", sel)
                save_clicked = True
                break
            except Exception:
                continue
        if not save_clicked:
            logger.warning("no save button — tags may not persist")
            return 4

        page.wait_for_timeout(8000)
        logger.info("done — tags should now be live on %s", NOTE_KEY)
        return 0
    finally:
        try:
            pub.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
