"""Diagnostic v11 (last): open selection mode, tick the 4 targets, then
dump EVERY actionable element (button/a/[role=button]) with non-empty
text + visibility, to find the post-selection confirm control (which is
NOT labelled 追加 -- the per-plan 追加 buttons vanish once articles are
checked).
"""
from __future__ import annotations

import json
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
SLUGS = ["nb8a49e7d42e5", "n927503f7e3a4", "n9d12f8cb9155", "n762c35e158ec"]


def main() -> int:
    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    pub._ensure_started()
    page = pub._page
    assert page is not None
    try:
        pub._assert_logged_in()
        page.goto("https://note.com/notes", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        page.locator("button[aria-label='その他']").first.click(timeout=4000)
        page.wait_for_timeout(800)
        page.locator("button:has-text('メンバーシップ特典追加')").first.click(timeout=3000)
        page.wait_for_timeout(2500)
        nchecked = 0
        for s in SLUGS:
            try:
                inp = page.locator(
                    f".o-articleList__item:has(a[href*='/n/{s}']) input.a-checkbox__field"
                ).first
                inp.wait_for(state="attached", timeout=4000)
                inp.evaluate("el => el.click()")
                page.wait_for_timeout(200)
                if inp.evaluate("el => el.checked"):
                    nchecked += 1
            except Exception as exc:
                print(f"tick {s} failed: {exc}")
        print(f"ticked {nchecked}/4")
        page.wait_for_timeout(1500)

        dump = page.evaluate(
            """() => {
                return [...document.querySelectorAll('button,a,[role=button]')]
                  .map(e => {
                    const r=e.getBoundingClientRect(); const st=getComputedStyle(e);
                    return {tag:e.tagName.toLowerCase(),
                            txt:(e.innerText||'').trim().slice(0,30),
                            al:(e.getAttribute('aria-label')||'').slice(0,30),
                            cls:(e.className||'').slice(0,40),
                            vis: st.display!=='none'&&st.visibility!=='hidden'&&r.width>0&&r.height>0,
                            y: Math.round(r.y)};
                  })
                  .filter(x => (x.txt || x.al) && x.vis)
                  .slice(0,50);
            }"""
        )
        print(json.dumps(dump, ensure_ascii=False, indent=2))
        _OUT = _REPO / "data" / "_diag"; _OUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(_OUT / "diag11_postcheck.png"), full_page=True)
        for s in SLUGS:
            try:
                inp = page.locator(
                    f".o-articleList__item:has(a[href*='/n/{s}']) input.a-checkbox__field"
                ).first
                if inp.evaluate("el => el.checked"):
                    inp.evaluate("el => el.click()")
            except Exception:
                pass
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
