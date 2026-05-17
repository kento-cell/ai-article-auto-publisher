"""Read-only CDP diagnostic for the note paid-price input drift bug.

Background: publishers/note_publisher.py:_set_price fills the price
field on the note publish-settings panel. As of 2026-05-15 all five
``price_input_selectors`` candidates miss the field, so the price stays
at the ¥300 placeholder (4 articles shipped underpriced). This script
attaches to the already-running Brave (CDP port from CHATGPT_CDP_PORT,
default 9222), opens ONE fresh tab on the edit page of an existing paid
article, walks the same flow as _set_price (公開設定 -> 有料 radio),
and dumps the *current* DOM of every nearby <input> so we can pick a
selector that actually matches.

It also probes the 有料 radio selectors.

STRICTLY read-only: never clicks 更新する / 公開. It DOES fill the
price input as a try-shot (then reads value back) — that only mutates
unsaved editor state, which is discarded when the tab closes.

Outputs:
  * console: input attributes (tag/type/inputmode/data-testid/
    placeholder/aria-label/name/class/parent-label-text)
  * screenshot -> data/_diag_note_price.png
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

_REPO = Path(__file__).resolve().parent.parent
_SHOT = _REPO / "data" / "_diag_note_price.png"
# BitLocker article (currently ¥300, should be ¥500) — paid, editable.
_ARTICLE_URL = "https://note.com/note-user/n/n66ebefddc10c"


def _note_id(url: str) -> str:
    import re
    m = re.search(r"/n/([a-zA-Z0-9]+)", url)
    if not m:
        raise SystemExit(f"cannot parse note id from {url}")
    return m.group(1)


# JS that snapshots every <input> on the page with the attributes we
# care about, plus the text of the closest enclosing <label> / section.
_DUMP_INPUTS_JS = r"""() => {
    const inputs = Array.from(document.querySelectorAll('input, textarea'));
    return inputs.map((el, i) => {
        const r = el.getBoundingClientRect();
        let labelText = '';
        const lbl = el.closest('label');
        if (lbl) labelText = (lbl.innerText || '').trim().slice(0, 60);
        if (!labelText && el.id) {
            const forLbl = document.querySelector(
                'label[for="' + CSS.escape(el.id) + '"]');
            if (forLbl) labelText = (forLbl.innerText || '').trim().slice(0,60);
        }
        // climb up to 3 ancestors for any nearby descriptive text
        let ctx = '';
        let p = el.parentElement;
        for (let d = 0; d < 4 && p; d++) {
            const t = (p.innerText || '').trim();
            if (t && t.length < 120) { ctx = t.replace(/\s+/g,' '); }
            p = p.parentElement;
        }
        return {
            idx: i,
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type'),
            inputmode: el.getAttribute('inputmode'),
            testid: el.getAttribute('data-testid'),
            placeholder: el.getAttribute('placeholder'),
            ariaLabel: el.getAttribute('aria-label'),
            name: el.getAttribute('name'),
            id: el.id || null,
            cls: (el.getAttribute('class') || '').slice(0, 120),
            value: (el.value || '').slice(0, 30),
            visible: r.width > 0 && r.height > 0,
            labelText: labelText,
            ctxText: ctx.slice(0, 80),
        };
    });
}"""


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

    page = ctx.new_page()
    try:
        page.set_default_timeout(60_000)
        note_id = _note_id(_ARTICLE_URL)
        edit_url = f"https://editor.note.com/notes/{note_id}/edit/"
        print(f"opening edit page: {edit_url}")
        page.goto(edit_url, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(5_000)
        print(f"landed on: {page.url}")
        if "login" in page.url or "enter" in page.url:
            print("WALL: redirected to login — Brave on 9222 is not "
                  "logged into note.com. Aborting.")
            return 1

        try:
            page.wait_for_selector(".ProseMirror", timeout=20_000)
            print("editor: ProseMirror ready")
        except Exception:  # noqa: BLE001
            print("WARN: ProseMirror not found (UI changed?)")

        # --- Step A: open 公開設定 ----------------------------------
        publish_btn_selectors = [
            "button:has-text('公開設定')",
            "button:has-text('公開に進む')",
            "[data-testid='publish-settings']",
        ]
        opened = False
        for sel in publish_btn_selectors:
            loc = page.locator(sel).first
            try:
                if loc.count() and loc.is_visible(timeout=3_000):
                    loc.click()
                    opened = True
                    print(f"公開設定: opened via {sel}")
                    break
            except Exception:  # noqa: BLE001
                continue
        if not opened:
            print("WARN: 公開設定 button not found — dumping inputs anyway")
        page.wait_for_timeout(3_000)

        # --- Step B: probe 有料 radio -------------------------------
        paid_radio_selectors = [
            "label:has-text('有料') input[type='radio']",
            "input[type='radio'][value='paid']",
            "label:has-text('有料')",
            "text=有料",
        ]
        print("\n=== 有料 radio selector probe ===")
        radio_hit = None
        for sel in paid_radio_selectors:
            try:
                loc = page.locator(sel).first
                cnt = loc.count()
                vis = bool(cnt) and loc.is_visible(timeout=1_500)
                print(f"  {'HIT ' if vis else '    '}count={cnt} "
                      f"visible={vis}  {sel}")
                if vis and radio_hit is None:
                    radio_hit = sel
            except Exception as exc:  # noqa: BLE001
                print(f"      err  {sel}  ({exc})")
        if radio_hit:
            print(f"  -> clicking 有料 via: {radio_hit}")
            try:
                loc = page.locator(radio_hit).first
                loc.scroll_into_view_if_needed(timeout=3_000)
                loc.click(timeout=3_000)
                page.wait_for_timeout(1_500)
            except Exception as exc:  # noqa: BLE001
                print(f"  WARN: 有料 click failed: {exc}")
        else:
            print("  WARN: no 有料 radio matched any selector")

        # --- Step C: dump every input after 有料 ---------------------
        print("\n=== INPUT / TEXTAREA snapshot (post-有料) ===")
        try:
            inputs = page.evaluate(_DUMP_INPUTS_JS)
        except Exception as exc:  # noqa: BLE001
            print(f"FATAL: input dump JS failed: {exc}")
            inputs = []
        for o in inputs:
            print(json.dumps(o, ensure_ascii=False))

        # --- Step D: probe current price selectors ------------------
        price_input_selectors = [
            "input[inputmode='numeric']",
            "input[type='number']",
            "[data-testid='price-input']",
            "input[placeholder*='100']",
            "label:has-text('価格') >> .. >> input",
        ]
        print("\n=== current price_input_selectors probe ===")
        for sel in price_input_selectors:
            try:
                loc = page.locator(sel).first
                cnt = loc.count()
                vis = bool(cnt) and loc.is_visible(timeout=1_000)
                print(f"  {'HIT ' if vis else 'MISS'} count={cnt} "
                      f"visible={vis}  {sel}")
            except Exception as exc:  # noqa: BLE001
                print(f"  err  {sel}  ({exc})")

        # --- Step E: try-shot — fill the best-guess price input -----
        # Candidate selectors we want to validate (broadest first).
        trial_selectors = [
            "input[inputmode='numeric']",
            "input[name*='price']",
            "input[id*='price']",
            "input[placeholder*='円']",
            "input[type='tel']",
        ]
        print("\n=== try-shot: fill price input with 500, read back ===")
        for sel in trial_selectors:
            try:
                loc = page.locator(sel).first
                if not loc.count() or not loc.is_visible(timeout=1_000):
                    print(f"  skip (not visible): {sel}")
                    continue
                loc.scroll_into_view_if_needed(timeout=2_000)
                loc.click(timeout=2_000)
                loc.fill("")
                loc.fill("500")
                page.wait_for_timeout(400)
                val = loc.input_value()
                print(f"  {'OK  ' if val.strip() in ('500','¥500','500円') else 'BAD '}"
                      f"value-after-fill={val!r}  via {sel}")
            except Exception as exc:  # noqa: BLE001
                print(f"  err  {sel}  ({exc})")

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
