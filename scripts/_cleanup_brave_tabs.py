"""One-shot orphan-tab sweep for the running Brave (CDP attach mode).

Closes any ``about:blank`` / ``chrome://newtab/`` tabs the image-gen
flow may have left behind. NEVER touches user pages — chatgpt.com,
google.com, amazon, etc. are all preserved.

Run with::

    py scripts/_cleanup_brave_tabs.py
"""
from __future__ import annotations

import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

CDP = "http://localhost:9222"
EMPTY_URLS = {"", "about:blank", "chrome://newtab/"}


def main() -> int:
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP)
        except Exception as exc:
            print(f"ERROR: cannot connect to {CDP}: {exc}")
            return 2

        if not browser.contexts:
            print("ERROR: no contexts")
            return 2
        ctx = browser.contexts[0]
        before = len(ctx.pages)
        closed: list[str] = []
        for pg in list(ctx.pages):
            try:
                url = pg.url or ""
                if url in EMPTY_URLS or url.startswith("about:"):
                    pg.close()
                    closed.append(url or "(empty)")
            except Exception as exc:
                print(f"  skip page (close failed): {exc}")
        after = len(ctx.pages)
        print(f"tabs before={before} after={after} closed={len(closed)}")
        for u in closed:
            print(f"  - closed: {u}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
