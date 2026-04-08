"""Test note article deletion from dashboard."""
from __future__ import annotations

import io
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

_ROOT = Path(__file__).resolve().parent.parent
PROFILE = _ROOT / "data" / "note-profile"

TARGET = "ne1541f6e53ed"  # John Deere article


def main() -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="msedge",
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://note.com/notes", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        # Find the card containing our target note and its その他 button
        result = page.evaluate(
            """(noteId) => {
                const links = Array.from(document.querySelectorAll('a[href*="' + noteId + '"]'));
                if (!links.length) return 'NO LINK';
                let el = links[0];
                while (el && el.parentElement) {
                    const btn = el.parentElement.querySelector('button[aria-label*="その他"]');
                    if (btn) {
                        btn.setAttribute('data-target-delete', '1');
                        return 'FOUND';
                    }
                    el = el.parentElement;
                }
                return 'NOT FOUND';
            }""",
            TARGET,
        )
        print(f"Find button: {result}")

        if result != "FOUND":
            page.screenshot(path=str(_ROOT / "logs" / "delete_find_failed.png"))
            ctx.close()
            return

        # Click the その他 button for this article
        btn = page.locator("button[data-target-delete='1']").first
        btn.click()
        page.wait_for_timeout(1500)

        # Dump menu items
        print("=== Menu items after clicking ===")
        items = page.locator("[role='menuitem']:visible, [role='menu'] *:visible").all()
        for item in items[:20]:
            try:
                text = item.evaluate("el => (el.textContent||'').trim().slice(0,50)")
                if text:
                    print(f"  {text}")
            except Exception:
                pass

        # Also dump all visible elements with "削除" text
        delete_els = page.locator(":text('削除'):visible").all()
        print(f"=== '削除' elements: {len(delete_els)} ===")
        for el in delete_els[:5]:
            try:
                info = el.evaluate(
                    "el => ({tag: el.tagName, text: el.textContent.trim().slice(0,40), role: el.getAttribute('role')})"
                )
                print(f"  {info}")
            except Exception:
                pass

        page.screenshot(path=str(_ROOT / "logs" / "delete_menu_opened.png"))
        page.wait_for_timeout(5000)
        ctx.close()


if __name__ == "__main__":
    main()
