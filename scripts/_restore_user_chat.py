"""Restore the user's working chat tab back to /c/<id>.

Earlier in this session a `pg.reload()` ran on every chatgpt.com tab,
and ChatGPT's frontend redirected /c/<id> URLs to bare /. That left
the user's working tab pointing at a brand-new composer with our
test prompt residue typed into it.

This script finds the bare ``chatgpt.com/`` tab and navigates it
back to the original ``/c/69e826ac-...`` (リモート作業環境提案) so
the user's session is preserved. Side-effect: composer residue gets
cleared, sidebar refreshes from server (so any cached "deleted"
chat ghost-rows disappear).
"""
from __future__ import annotations

import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

CDP = "http://localhost:9222"
USER_WORKING_CHAT = (
    "https://chatgpt.com/c/69e826ac-05a4-83a2-83ee-195fcc69b324"
)


def main() -> int:
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP)
        except Exception as exc:
            print(f"ERROR: cannot connect: {exc}")
            return 2
        ctx = browser.contexts[0]
        target_pages = []
        for pg in ctx.pages:
            try:
                url = (pg.url or "").rstrip("/")
                if url == "https://chatgpt.com":
                    target_pages.append(pg)
            except Exception:
                continue
        if not target_pages:
            # No bare chatgpt.com to overwrite — instead OPEN a fresh
            # tab on the user's working chat. Without this, a Brave
            # kill/restart cycle (which we do during note-publisher
            # edits) leaves the user with zero chatgpt.com tabs even
            # though their session is intact server-side.
            print("no bare chatgpt.com tab — opening fresh tab on working chat")
            try:
                pg = ctx.new_page()
                pg.goto(
                    USER_WORKING_CHAT,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                print(f"opened: {pg.url}")
            except Exception as exc:
                print(f"  failed: {exc}")
            return 0

        for pg in target_pages:
            try:
                pg.goto(
                    USER_WORKING_CHAT,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                print(f"restored: {pg.url}")
            except Exception as exc:
                print(f"  failed: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
