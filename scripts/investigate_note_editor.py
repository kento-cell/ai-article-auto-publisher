"""Investigate note.com editor image upload mechanism.

Launches note.com in non-headless mode with the persistent profile,
navigates to the new-article editor, and dumps DOM structure around
image-related controls so we can figure out:

  1. How to insert an image inline into the body
  2. How to dismiss the CropModal that blocks interaction
  3. The full click sequence needed end-to-end

Usage:
    venv/Scripts/python.exe scripts/investigate_note_editor.py

The browser is left OPEN at the end so a human can poke around.
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

# Force UTF-8 stdout so Japanese text prints correctly on Windows cp932.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = REPO_ROOT / "data" / "note-profile"
STOCK_DIR = REPO_ROOT / "data" / "images" / "stock"
LOG_DIR = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def banner(msg: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {msg}")
    print("=" * 70)


def ensure_test_image() -> Path:
    """Return a path to a small test image; create one if needed."""
    existing = list(STOCK_DIR.glob("*.jpg")) + list(STOCK_DIR.glob("*.png"))
    if existing:
        print(f"[test-image] using existing: {existing[0]}")
        return existing[0]

    # Fallback: create a tiny PNG with PIL
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise RuntimeError("No test image and PIL not available")

    STOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = STOCK_DIR / "investigate_test.png"
    img = Image.new("RGB", (800, 600), color=(70, 130, 180))
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 100, 700, 500], outline=(255, 255, 255), width=8)
    draw.text((200, 280), "NOTE TEST IMAGE", fill=(255, 255, 255))
    img.save(path)
    print(f"[test-image] created: {path}")
    return path


def dump_element(page, selector: str, label: str, limit: int = 30) -> None:
    """Print attributes of every element matching selector."""
    banner(f"DOM DUMP: {label}  ({selector})")
    try:
        els = page.locator(selector).all()
    except Exception as exc:
        print(f"  locator failed: {exc}")
        return
    print(f"  count = {len(els)}")
    for i, el in enumerate(els[:limit]):
        try:
            info = el.evaluate(
                """el => ({
                    tag: el.tagName,
                    text: (el.textContent || '').trim().slice(0, 60),
                    aria_label: el.getAttribute('aria-label'),
                    aria_haspopup: el.getAttribute('aria-haspopup'),
                    title: el.getAttribute('title'),
                    data_testid: el.getAttribute('data-testid'),
                    type: el.getAttribute('type'),
                    cls: (el.className || '').toString().slice(0, 120),
                    visible: !!(el.offsetParent || el.getClientRects().length),
                })"""
            )
            print(f"  [{i:02d}] {json.dumps(info, ensure_ascii=False)}")
        except Exception as exc:
            print(f"  [{i:02d}] evaluate failed: {exc}")


def main() -> None:
    if not PROFILE_DIR.exists():
        raise SystemExit(
            "data/note-profile/ not found. Run scripts/note_login.py first."
        )

    test_image = ensure_test_image()
    print(f"[main] test image = {test_image}")

    with sync_playwright() as pw:
        banner("LAUNCHING BROWSER (headless=False, msedge, persistent)")
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="msedge",
            headless=False,
            viewport={"width": 1400, "height": 960},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
            ],
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        context.set_default_timeout(20_000)

        page = context.pages[0] if context.pages else context.new_page()

        # ------------------------------------------------------------------
        # 1. Navigate to editor
        # ------------------------------------------------------------------
        banner("STEP 1: navigate to /notes/new")
        page.goto("https://note.com/notes/new", wait_until="domcontentloaded")
        print(f"  current url = {page.url}")
        if "/login" in page.url:
            raise SystemExit("Session expired. Run scripts/note_login.py.")

        page.wait_for_selector(".ProseMirror, [contenteditable='true']", timeout=30_000)
        page.wait_for_timeout(1500)

        # ------------------------------------------------------------------
        # 2. Type a title + click into body
        # ------------------------------------------------------------------
        banner("STEP 2: input title + focus body")
        try:
            title = page.locator(
                "textarea[placeholder*='タイトル'], input[placeholder*='タイトル']"
            ).first
            title.click()
            title.type("画像調査テスト", delay=20)
            print("  title typed")
        except Exception as exc:
            print(f"  title input failed: {exc}")

        body = page.locator(".ProseMirror").first
        body.click()
        page.keyboard.type("ここに画像を挿入する予定です。\n\n", delay=10)
        page.wait_for_timeout(800)

        # ------------------------------------------------------------------
        # 3. Dump all buttons + all file inputs BEFORE any image click
        # ------------------------------------------------------------------
        dump_element(page, "button", "ALL BUTTONS (before image upload)", limit=80)
        dump_element(page, "input[type='file']", "FILE INPUTS", limit=10)
        dump_element(
            page,
            "[aria-label*='画像'], [aria-label*='image'], [aria-label*='Image']",
            "image-labelled elements",
        )

        # ------------------------------------------------------------------
        # 4. Look for the '+' floating toolbar that appears on empty lines
        # ------------------------------------------------------------------
        banner("STEP 4: looking for floating '+' toolbar on empty line")
        # Ensure we're on a fresh empty line
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        page.wait_for_timeout(600)

        # note's editor typically shows a '+' add-block button to the left
        # of empty ProseMirror lines. Try a range of selectors.
        plus_selectors = [
            "button[aria-label*='追加']",
            "button[aria-label*='add']",
            "button[aria-label*='Add']",
            "button[aria-label*='挿入']",
            "button[aria-label*='メニュー']",
            "[class*='MediaButton']",
            "[class*='AddBlock']",
            "[class*='PlusButton']",
            "[class*='floating']",
            "[class*='toolbar'] button",
        ]
        for sel in plus_selectors:
            try:
                els = page.locator(sel).all()
                if els:
                    print(f"  [{sel}] -> {len(els)} elements")
                    for i, el in enumerate(els[:5]):
                        try:
                            info = el.evaluate(
                                """el => ({
                                    text: (el.textContent || '').trim().slice(0, 40),
                                    aria: el.getAttribute('aria-label'),
                                    cls: (el.className || '').toString().slice(0, 100),
                                    visible: !!(el.offsetParent),
                                })"""
                            )
                            print(f"     [{i}] {info}")
                        except Exception:
                            pass
            except Exception as exc:
                print(f"  [{sel}] err: {exc}")

        # ------------------------------------------------------------------
        # 5. Attempt upload
        #
        # Findings from the first run:
        #   - There is NO input[type=file] in the DOM until we trigger upload.
        #   - Clicking button[aria-label='画像を追加'] opens a menu containing
        #     buttons with text: 画像 / 動画 / 埋め込み / ファイル
        #   - So the flow is: click 画像を追加 -> click 画像 -> filechooser
        # ------------------------------------------------------------------
        banner("STEP 5: click 画像を追加 -> 画像 -> set file")
        uploaded = False

        add_image_btn = page.locator("button[aria-label='画像を追加']").first
        try:
            add_image_btn.scroll_into_view_if_needed(timeout=3000)
            add_image_btn.click(timeout=3000)
            print("  clicked 画像を追加 (add-block button)")
            page.wait_for_timeout(800)
        except Exception as exc:
            print(f"  !! failed to click 画像を追加: {exc}")

        # Dump what appeared after the click
        dump_element(
            page,
            "button",
            "buttons visible AFTER clicking 画像を追加",
            limit=40,
        )

        # The menu item is the button with text '画像'
        image_menu_item = page.locator("button:has-text('画像')").filter(
            has_not_text="画像を"
        ).first
        print("  looking for 画像 menu item and expecting filechooser...")
        try:
            with page.expect_file_chooser(timeout=6_000) as fc_info:
                image_menu_item.click(timeout=3000)
            chooser = fc_info.value
            chooser.set_files(str(test_image))
            print(f"  -> FILE CHOSEN: {test_image}")
            uploaded = True
        except Exception as exc:
            print(f"  !! 画像 menu click+filechooser failed: {exc}")

        # Fallback: after click, check if an input[type=file] was injected
        if not uploaded:
            page.wait_for_timeout(500)
            fis = page.locator("input[type='file']").all()
            print(f"  fallback: found {len(fis)} file inputs post-click")
            for i, fi in enumerate(fis):
                try:
                    fi.set_input_files(str(test_image))
                    print(f"  -> set files on input[type=file] #{i}")
                    uploaded = True
                    break
                except Exception as exc:
                    print(f"  [{i}] set_input_files failed: {exc}")

        # ------------------------------------------------------------------
        # 6. Wait for CropModal to appear + dump its structure
        # ------------------------------------------------------------------
        banner("STEP 6: waiting for CropModal to appear")
        # Give the upload + modal animation time.
        page.wait_for_timeout(4000)

        crop_selectors = [
            "[class*='CropModal']",
            "[class*='cropModal']",
            "[class*='ImageCrop']",
            "[class*='crop']",
            "[class*='Crop']",
            "[role='dialog']",
            ".o-modal",
            "[class*='Modal']",
        ]
        found_modal = None
        for sel in crop_selectors:
            try:
                els = page.locator(sel).all()
                visible_count = 0
                for el in els:
                    try:
                        if el.is_visible(timeout=200):
                            visible_count += 1
                    except Exception:
                        pass
                if visible_count:
                    print(f"  [{sel}] -> {len(els)} total, {visible_count} visible")
                    if found_modal is None:
                        found_modal = sel
            except Exception:
                continue

        # Also dump ALL role=dialog content so we can distinguish CropModal
        # from the 'AIと相談' dialog we saw in the first run.
        banner("STEP 6b: dumping all role=dialog contents")
        dialogs = page.locator("[role='dialog']").all()
        print(f"  total dialogs = {len(dialogs)}")
        for i, dlg in enumerate(dialogs):
            try:
                info = dlg.evaluate(
                    """el => ({
                        visible: !!(el.offsetParent || el.getClientRects().length),
                        text: (el.textContent || '').trim().slice(0, 150),
                        cls: (el.className || '').toString().slice(0, 140),
                        btnCount: el.querySelectorAll('button').length,
                        hasImg: !!el.querySelector('img'),
                        hasCanvas: !!el.querySelector('canvas'),
                        hasSlider: !!el.querySelector('[role="slider"], input[type="range"]'),
                    })"""
                )
                print(f"  [dlg {i}] {json.dumps(info, ensure_ascii=False)}")
            except Exception as exc:
                print(f"  [dlg {i}] evaluate failed: {exc}")

        if found_modal:
            print(f"  -> treating modal root: {found_modal}")
            dump_element(page, f"{found_modal} button", "MODAL BUTTONS", limit=30)
            # Also dump the entire HTML of the first modal for inspection
            try:
                html = page.locator(found_modal).first.evaluate(
                    "el => el.outerHTML.slice(0, 4000)"
                )
                print("  -- modal outerHTML (first 4000 chars) --")
                print(html)
            except Exception as exc:
                print(f"  could not dump HTML: {exc}")
        else:
            print("  !! no CropModal detected")
            dump_element(
                page,
                "[role='dialog']",
                "any role=dialog elements (fallback)",
                limit=5,
            )

        # ------------------------------------------------------------------
        # 7. Try clicking the confirm button
        # ------------------------------------------------------------------
        banner("STEP 7: attempt to dismiss CropModal")
        confirm_tried = [
            "button:has-text('保存')",
            "button:has-text('完了')",
            "button:has-text('適用')",
            "button:has-text('決定')",
            "button:has-text('確定')",
            "button:has-text('OK')",
            "button:has-text('トリミング')",
            "button:has-text('挿入')",
            "[class*='CropModal'] button[type='submit']",
        ]
        for sel in confirm_tried:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=400):
                    info = btn.evaluate(
                        """el => ({
                            text: el.textContent.trim(),
                            cls: (el.className || '').toString().slice(0, 100),
                        })"""
                    )
                    print(f"  [{sel}] VISIBLE -> {info}")
                    btn.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    # Did the modal close?
                    still_open = False
                    if found_modal:
                        try:
                            still_open = page.locator(found_modal).first.is_visible(
                                timeout=400
                            )
                        except Exception:
                            still_open = False
                    print(f"  -> modal still open? {still_open}")
                    if not still_open:
                        print(f"  SUCCESS: crop modal dismissed via {sel}")
                        break
            except Exception as exc:
                print(f"  [{sel}] failed: {exc}")

        # ------------------------------------------------------------------
        # 8. Verify image is now in the body
        # ------------------------------------------------------------------
        banner("STEP 8: verify image embedded in body")
        page.wait_for_timeout(1500)
        try:
            imgs = page.locator(".ProseMirror img").all()
            print(f"  .ProseMirror img count = {len(imgs)}")
            for i, img in enumerate(imgs[:5]):
                info = img.evaluate(
                    """el => ({
                        src: (el.src || '').slice(0, 120),
                        alt: el.alt,
                        cls: (el.className || '').toString().slice(0, 100),
                    })"""
                )
                print(f"  [{i}] {info}")
        except Exception as exc:
            print(f"  verify failed: {exc}")

        # Screenshot for the record
        try:
            shot = LOG_DIR / "investigate_note_editor.png"
            page.screenshot(path=str(shot), full_page=True)
            print(f"  screenshot -> {shot}")
        except Exception as exc:
            print(f"  screenshot failed: {exc}")

        banner("DONE - browser left open. Ctrl+C to exit.")
        # Park the script so the window stays open for manual inspection.
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nexiting on Ctrl+C")
            context.close()


if __name__ == "__main__":
    main()
