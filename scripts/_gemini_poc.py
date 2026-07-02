"""PoC: Playwright + Brave CDP → gemini.google.com で画像生成 → blob をローカル保存。

Success = data/images/gemini_poc_TIMESTAMP.png が実際に作成される。
2026-07-02 Claude in Chrome の <a download> 経路が Chrome 拡張 sandbox で
発火しないと判明したのを受け、Playwright なら blob → download が動くかを
検証するための最小コード。動けば案 B (画像生成先を ChatGPT→Gemini に切替、
note publish は Playwright 継続) の実装可能性が確定する。
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for ln in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemini_poc")

from playwright.sync_api import sync_playwright

CDP_PORT = int(os.environ.get("CHATGPT_CDP_PORT", "9222"))
GEMINI_URL = "https://gemini.google.com/app"
OUT_DIR = _REPO / "data" / "images" / "poc"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROMPT = (
    "画像を生成してください: cozy home workspace with laptop and coffee, "
    "watercolor style, warm morning light, muted tones, 16:9 landscape."
)


def main() -> int:
    log.info("Connecting to Brave CDP at http://127.0.0.1:%d", CDP_PORT)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.new_page()
        try:
            log.info("Navigating to %s", GEMINI_URL)
            page.goto(GEMINI_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)

            # Dismiss any "留意点" dialog if it appears
            try:
                ok = page.locator("button:has-text('OK')").first
                if ok.is_visible(timeout=2000):
                    ok.click()
                    log.info("Dismissed 留意点 dialog")
                    page.wait_for_timeout(500)
            except Exception:
                pass

            # Prompt textarea (multiple selectors as Gemini renames)
            selectors = [
                "textarea[aria-label*='Gemini']",
                "textarea[placeholder*='Gemini']",
                "div[contenteditable='true'][role='textbox']",
                "rich-textarea div[contenteditable='true']",
            ]
            entered = False
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=1500):
                        loc.click()
                        # Real keystrokes so React onChange fires
                        page.keyboard.type(PROMPT, delay=15)
                        entered = True
                        log.info("Prompt entered via selector: %s", sel)
                        break
                except Exception as exc:  # noqa: BLE001
                    log.debug("selector %s failed: %s", sel, exc)
            if not entered:
                log.error("Could not find prompt input")
                page.screenshot(path=str(OUT_DIR / "poc_input_fail.png"))
                return 1

            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            log.info("Prompt sent, waiting for image generation")

            # Wait until a blob:https://gemini.google.com/* img appears with
            # naturalWidth >= 512. Poll up to 90 s.
            deadline = time.time() + 90
            blob_url: str | None = None
            while time.time() < deadline:
                try:
                    blob_url = page.evaluate("""
                        () => {
                          const imgs = Array.from(document.querySelectorAll('img'));
                          const g = imgs.find(i => i.src.startsWith('blob:') && i.naturalWidth >= 512);
                          return g ? g.src : null;
                        }
                    """)
                except Exception:
                    blob_url = None
                if blob_url:
                    log.info("Image ready: %s", blob_url)
                    break
                page.wait_for_timeout(1500)
            if not blob_url:
                log.error("Timed out waiting for generated image")
                page.screenshot(path=str(OUT_DIR / "poc_gen_timeout.png"))
                return 2

            # blob: URLs can't be fetched cross-origin from Playwright's
            # UtilityScript frame; draw the already-rendered <img> element
            # onto a canvas and read via toDataURL — the img is same-origin
            # from the page's perspective and canvas.toDataURL bypasses
            # the fetch() CORS boundary.
            log.info("Reading blob content via canvas.toDataURL")
            b64 = page.evaluate("""
                () => {
                  const img = Array.from(document.querySelectorAll('img'))
                    .find(i => i.src.startsWith('blob:') && i.naturalWidth >= 512);
                  if (!img) return null;
                  const c = document.createElement('canvas');
                  c.width = img.naturalWidth;
                  c.height = img.naturalHeight;
                  const g = c.getContext('2d');
                  g.drawImage(img, 0, 0);
                  // Gemini PNGs come as PNG in blob; keep PNG
                  const dataUrl = c.toDataURL('image/png');
                  return dataUrl.split(',')[1] || null;
                }
            """)
            if not b64:
                log.error("blob->base64 returned empty")
                return 3

            import base64
            data = base64.b64decode(b64)
            out = OUT_DIR / f"gemini_poc_{int(time.time())}.png"
            out.write_bytes(data)
            log.info("SAVED %d bytes -> %s", len(data), out)
            return 0
        finally:
            try:
                page.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
