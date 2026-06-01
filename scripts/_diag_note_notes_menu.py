"""Diagnostic v3 (read-only): on the note "自分の記事" page
(https://note.com/notes), dump how each article row exposes its slug and
its「その他」(⋮) menu, then open the first row's menu and dump the menu
items — so we can confirm the exact "メンバーシップに追加" item text and
the row-locating selector before rewriting
``NotePublisher._add_to_memberships_via_dashboard``.

Does NOT add anything to a membership — it only opens one ⋮ menu and
reads it, then closes.

Run headed:
    py scripts/_diag_note_notes_menu.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_OUT = _REPO / "data" / "_diag"


def main() -> int:
    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    pub._ensure_started()
    assert pub._page is not None
    page = pub._page
    try:
        try:
            pub._assert_logged_in()
            print("[login] OK")
        except Exception as exc:
            print(f"[login] WARNING: {exc}")

        print("\n>>> goto https://note.com/notes")
        page.goto("https://note.com/notes", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)

        # Dump article rows: title, slug, and whether an その他 button is near.
        rows = page.evaluate(
            """() => {
                // Each article row: find anchors to /<user>/n/<slug> or /n/<slug>
                const out = [];
                const arts = Array.from(document.querySelectorAll('article, li, div'))
                    .filter(el => el.querySelector("a[href*='/n/']") &&
                                  el.querySelector("button"));
                const seen = new Set();
                for (const el of arts) {
                    const a = el.querySelector("a[href*='/n/']");
                    if (!a) continue;
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/\\/n\\/([a-zA-Z0-9]+)/);
                    const slug = m ? m[1] : '';
                    if (!slug || seen.has(slug)) continue;
                    seen.add(slug);
                    const moreBtns = Array.from(el.querySelectorAll('button'))
                        .map(b => b.getAttribute('aria-label') || (b.innerText||'').trim())
                        .filter(Boolean);
                    out.push({slug, title:(a.innerText||'').trim().slice(0,40),
                              href, btns: moreBtns.slice(0,6)});
                    if (out.length >= 8) break;
                }
                return out;
            }"""
        ) or []
        print(f"\n--- article rows ({len(rows)}) ---")
        for r in rows:
            print(f"  slug={r['slug']:14} btns={r['btns']} title={r['title']!r}")

        # Open the FIRST article's その他 menu and dump items.
        opened = False
        try:
            first_more = page.locator("button[aria-label='その他']").first
            if first_more.count() > 0:
                first_more.scroll_into_view_if_needed()
                first_more.click(timeout=3000)
                page.wait_for_timeout(1200)
                opened = True
                print("\n>>> opened first その他 menu")
        except Exception as exc:
            print(f"  could not open その他 menu: {exc}")

        if opened:
            items = page.evaluate(
                """() => {
                    const sels = "[role=menuitem],[role=menu] *,[role=dialog] button,[role=dialog] a";
                    return Array.from(document.querySelectorAll(sels))
                        .map(e => (e.innerText||'').trim())
                        .filter(Boolean).slice(0,40);
                }"""
            ) or []
            print(f"\n--- menu items ({len(items)}) ---")
            for t in items:
                print(f"  M | {t!r}")

        _OUT.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(_OUT / "diag3_notes_menu.png"), full_page=True)
            (_OUT / "diag3_notes_menu.html").write_text(page.content(), encoding="utf-8")
            print("  [saved] diag3_notes_menu.png/.html")
        except Exception as exc:
            print(f"  (save failed: {exc})")
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
