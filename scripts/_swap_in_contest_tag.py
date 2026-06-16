"""One-shot: swap #生成AI out for #AIで遊ぼう on the contest entry.

DOM inspection (2026-06-17 00:31) revealed:
  * note hashtag UI hard caps at 5 tags
  * currently registered: #ChatGPT, #生成AI, #AI活用, #Claude, #AIフェスティバル
  * #AIで遊ぼう (CONTEST-REQUIRED) cannot fit
  * each existing tag is a button with a 削除 (aria-label) close icon
  * a separate 「追加」 button commits typed input (Enter alone doesn't)

This script:
  1. Opens the publish-settings panel
  2. Clicks the 削除 icon on the #生成AI chip
  3. Types AIで遊ぼう in the input
  4. Clicks the 追加 button
  5. Clicks 更新する to save
"""
from __future__ import annotations
import os, sys, logging
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for ln in (_REPO/".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.startswith("#"):
        k,v = ln.split("=",1); os.environ.setdefault(k.strip(), v.strip())
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("swap")
from publishers.note_publisher import NotePublisher

NOTE_KEY = "n444be2daa2ef"
TAG_TO_DROP = "生成AI"
TAG_TO_ADD = "AIで遊ぼう"


def main() -> int:
    pub = NotePublisher(headless=False)
    try:
        pub._ensure_started()
        page = pub._page
        pub._assert_logged_in()
        page.goto(f"https://editor.note.com/notes/{NOTE_KEY}/edit/",
                  wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(4000)
        page.locator("button:has-text('公開に進む')").first.click(timeout=8000)
        page.wait_for_timeout(5000)
        log.info("on: %s", page.url)

        # Step 1: delete the #生成AI tag chip if still present (re-run safe).
        drop_chip = page.locator(
            f"button:has-text('#{TAG_TO_DROP}') span[aria-label='削除']"
        ).first
        try:
            drop_chip.wait_for(state="visible", timeout=3_000)
            drop_chip.click(timeout=3_000)
            log.info("deleted chip: #%s", TAG_TO_DROP)
            page.wait_for_timeout(1500)
        except Exception:
            log.info("#%s already absent (skip delete)", TAG_TO_DROP)

        # Step 2: type the new tag in the input. Use fill() not type() —
        # fill sets the input value directly and triggers React/Vue's
        # onChange, which is what the "追加" button reads to enable itself.
        # The hashtag input lives inside <section> whose <h3> has id=hashtag.
        hashtag_section = page.locator("section:has(h3#hashtag)").first
        tag_inp = hashtag_section.locator("input[placeholder*='ハッシュタグ']").first
        tag_inp.wait_for(state="visible", timeout=5_000)
        tag_inp.click()
        page.wait_for_timeout(400)
        tag_inp.fill(TAG_TO_ADD)
        page.wait_for_timeout(1200)
        log.info("filled: %s | input value=%r", TAG_TO_ADD, tag_inp.input_value())

        # Step 3: click the 追加 button scoped to the hashtag section only,
        # NOT page-wide (page-wide matches "記事の追加" too). Use text-is
        # so the exact "追加" wins.
        add_btn = hashtag_section.get_by_role("button", name="追加", exact=True).first
        try:
            add_btn.wait_for(state="visible", timeout=5_000)
            add_btn.click(timeout=3_000)
            log.info("clicked exact 追加 (scoped)")
            page.wait_for_timeout(2500)
        except Exception as exc:
            log.warning("scoped 追加 click failed (%s) — Enter fallback", exc)
            tag_inp.press("Enter")
            page.wait_for_timeout(2000)

        # Step 4: confirm the new chip exists
        try:
            page.locator(f"button:has-text('#{TAG_TO_ADD}')").first.wait_for(
                state="visible", timeout=5_000)
            log.info("CONFIRM: #%s chip present in DOM", TAG_TO_ADD)
        except Exception:
            log.warning("could not see #%s chip — but pressing save anyway", TAG_TO_ADD)

        page.wait_for_timeout(2000)

        # Step 5: save
        for sel in ["button:has-text('更新する')",
                    "button:has-text('公開する')",
                    "button:has-text('公開')"]:
            try:
                page.locator(sel).first.click(timeout=3_000)
                log.info("save clicked: %s", sel)
                break
            except Exception:
                continue
        page.wait_for_timeout(8000)
        log.info("done")
        return 0
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
