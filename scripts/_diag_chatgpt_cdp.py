"""Read-only CDP diagnostic for the ChatGPT image pipeline.

Attaches to the already-running Brave (CDP port from CHATGPT_CDP_PORT,
default 9222), opens ONE fresh tab on chatgpt.com, and reports:

  * whether the composer (prompt-textarea) is reachable -> logged in
  * whether a login / Cloudflare-Turnstile wall is up instead
  * how many <img> elements the _wait_for_image selector would match,
    and what their src/size/alt are (to spot the note-logo placeholder)
  * a full-page screenshot -> data/_diag_chatgpt.png

Does NOT send any prompt, does NOT post anything, does NOT touch the
user's existing tabs. The new tab is closed at the end.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

_REPO = Path(__file__).resolve().parent.parent
_SHOT = _REPO / "data" / "_diag_chatgpt.png"


def main() -> int:
    port = os.environ.get("CHATGPT_CDP_PORT", "9222")
    cdp_url = f"http://localhost:{port}"
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: cannot CDP-attach to {cdp_url}: {exc}")
        pw.stop()
        return 1

    if not browser.contexts:
        print("FATAL: CDP browser exposed no contexts")
        browser.close()
        pw.stop()
        return 1
    ctx = browser.contexts[0]
    print(f"attached: {cdp_url} | {len(ctx.pages)} existing tab(s)")
    for pg in ctx.pages:
        print(f"  existing: {(pg.url or '')[:90]}")

    page = ctx.new_page()
    try:
        page.set_default_timeout(60_000)
        page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(4_000)
        print(f"\nlanded on: {page.url}")
        print(f"title    : {page.title()}")

        # Composer probe.
        composer_visible = False
        for sel in ("#prompt-textarea", "div[contenteditable='true']"):
            loc = page.locator(sel).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    composer_visible = True
                    print(f"composer : VISIBLE via {sel}  -> logged in")
                    break
            except Exception:  # noqa: BLE001
                pass
        if not composer_visible:
            print("composer : NOT visible -> likely login wall / Turnstile")

        # Login-wall / Turnstile probe.
        for label, sel in (
            ("login button", "button:has-text('Log in'), "
                              "button:has-text('ログイン'), "
                              "a:has-text('Log in')"),
            ("Turnstile iframe", "iframe[src*='challenges.cloudflare.com']"),
            ("signup wall", "button:has-text('Sign up')"),
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    print(f"WALL     : {label} present ({sel})")
            except Exception:  # noqa: BLE001
                pass

        # Replicate the FIXED _wait_for_image selector to confirm it
        # returns 0 candidates on a blank page (no assistant turn ->
        # null, sidebar gizmo avatars excluded).
        candidates = page.evaluate(
            """() => {
                const turns = document.querySelectorAll(
                    '[data-message-author-role="assistant"]'
                );
                if (!turns.length) return [];
                const root = turns[turns.length - 1];
                const imgs = Array.from(root.querySelectorAll('img'));
                return imgs
                    .filter(img => !img.closest('nav'))
                    .map(img => ({
                        src: (img.src || '').slice(0, 110),
                        w: img.naturalWidth || img.width || 0,
                        h: img.naturalHeight || img.height || 0,
                        alt: img.alt || '',
                    })).filter(o =>
                        o.src
                        && (o.src.startsWith('https://')
                            || o.src.startsWith('blob:'))
                        && o.w >= 200 && o.h >= 200
                        && !/avatar|sprite|emoji|icon/.test(o.src)
                        && !/[?&]gizmo_id=/.test(o.src)
                    );
            }"""
        )
        print(f"\nFIXED _wait_for_image candidates on a blank chatgpt.com: "
              f"{len(candidates)} (expect 0)")
        for c in candidates:
            print(f"  {c['w']}x{c['h']}  alt={c['alt'][:40]!r}  {c['src']}")
        assistant_turns = page.evaluate(
            "() => document.querySelectorAll("
            "'[data-message-author-role=\"assistant\"]').length"
        )
        print(f"assistant turns present: {assistant_turns}")

        _SHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(_SHOT), full_page=True)
        print(f"\nscreenshot saved: {_SHOT}")
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        browser.close()
        pw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
