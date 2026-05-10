"""Probe ChatGPT image-gen rate limit via CDP attach.

Connects to a running Brave (started with --remote-debugging-port=9222)
and opens a NEW tab on chatgpt.com — leaves every existing tab alone.
Sends a tiny image-gen prompt and reports what comes back:

  * "image-ok": got an <img> URL → rate limit cleared
  * "rate-limited": detected the red banner / send-button stuck
  * "error: <msg>": anything else (no auth, page didn't load, etc.)

Closes ONLY the tab it created. Never touches user's tabs.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from playwright.sync_api import sync_playwright  # noqa: E402

CDP_URL = "http://localhost:9222"
TEST_PROMPT = (
    "シンプルな水彩アニメ調で、白い猫がノートPCの前に座っている画像を1枚"
    "生成してください。1024×1024 正方形。"
)


def main() -> int:
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as exc:
            print(f"ERROR: cannot connect to CDP at {CDP_URL}: {exc}")
            return 2

        if not browser.contexts:
            print("ERROR: no browser contexts available")
            return 2
        ctx = browser.contexts[0]

        existing = list(ctx.pages)
        existing_urls = [p.url for p in existing]
        print(f"existing tabs: {len(existing)}")
        for u in existing_urls[:10]:
            print(f"  - {u[:100]}")

        # Open a fresh tab — never touch the existing pages.
        page = ctx.new_page()
        try:
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

            # Check for "rate limit" banner / paywall messaging up front.
            banner_text = page.evaluate(
                """() => {
                    const txt = document.body.innerText || '';
                    return txt.slice(0, 4000);
                }"""
            )
            print(f"page snapshot: {len(banner_text)} chars")
            for marker in (
                "画像生成", "上限", "rate", "limit",
                "Try again", "再試行", "later",
            ):
                if marker.lower() in banner_text.lower():
                    print(f"  marker hit: '{marker}'")

            # Find the prompt textarea / contenteditable.
            sel = "#prompt-textarea, div[contenteditable='true']"
            try:
                page.wait_for_selector(sel, timeout=15_000, state="visible")
            except Exception as exc:
                print(f"ERROR: composer not found: {exc}")
                return 3

            page.fill(sel, TEST_PROMPT) if "textarea" in sel else None
            # ContentEditable: focus + type
            page.click(sel)
            page.keyboard.type(TEST_PROMPT, delay=10)
            page.wait_for_timeout(800)

            # Try clicking the send button.
            send_sel = "button[data-testid='send-button']"
            try:
                page.wait_for_selector(send_sel, timeout=8_000, state="visible")
                page.click(send_sel)
                print("  → send button clicked")
            except Exception as exc:
                print(f"  → send button not visible in 8s: {exc}")
                # Try Enter as fallback.
                page.keyboard.press("Enter")
                print("  → fallback: pressed Enter")

            # Wait up to 90s for either an <img> or a banner.
            deadline = time.time() + 90
            verdict = "timeout"
            while time.time() < deadline:
                state = page.evaluate(
                    """() => {
                        const imgs = document.querySelectorAll(
                            '[data-message-author-role="assistant"] img'
                        );
                        const text = (document.body.innerText || '').toLowerCase();
                        return {
                            imgCount: imgs.length,
                            firstSrc: imgs[0]?.src || null,
                            hasRateBanner: (
                                text.includes('画像生成') &&
                                (text.includes('上限') || text.includes('しばらく'))
                            ) || text.includes('rate limit'),
                        };
                    }"""
                )
                if state.get("imgCount", 0) > 0:
                    verdict = "image-ok"
                    print(f"  imgCount={state['imgCount']} src={state.get('firstSrc')[:120] if state.get('firstSrc') else 'n/a'}")
                    break
                if state.get("hasRateBanner"):
                    verdict = "rate-limited"
                    break
                time.sleep(2)

            print(f"VERDICT: {verdict}")

            # Save screenshot for human review.
            ts = time.strftime("%Y%m%d_%H%M%S")
            shot_path = (
                _REPO / "data" / "images" / "covers"
                / f"_cdp_probe_{ts}_{verdict}.png"
            )
            shot_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shot_path), full_page=False)
            print(f"screenshot: {shot_path}")
            return 0 if verdict == "image-ok" else 1
        finally:
            try:
                page.close()
                print("probe tab closed")
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
