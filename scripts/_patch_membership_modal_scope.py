"""One-shot patch: the per-plan 「追加」 control is an <a class=a-button>,
not a <button>, so the button-only scan found nothing. Broaden the
locator to button/a/[role=button] and require the element's own text to
be exactly 「追加」 before matching it to a plan by surrounding text.
"""
from __future__ import annotations
from pathlib import Path

T = Path(__file__).resolve().parent.parent / "publishers" / "note_publisher.py"
src = T.read_text(encoding="utf-8")

OLD = '''            btns = page.locator("button", has_text="追加")
            count = btns.count()
            for i in range(count):
                b = btns.nth(i)
                try:
                    ctx = b.evaluate(
                        "el => { let e=el; for(let i=0;i<6 && e && e.parentElement;"
                        " i++){ e=e.parentElement; const t=(e.innerText||'').trim();"
                        " if(t.length>4) return t; } return ''; }"
                    )
                except (PlaywrightTimeoutError, PlaywrightError):
                    ctx = ""
                if plan_name in (ctx or ""):
                    add_btn = b
                    break'''

NEW = '''            btns = page.locator(
                "button:has-text('追加'), a:has-text('追加'), "
                "[role=button]:has-text('追加')"
            )
            count = btns.count()
            for i in range(count):
                b = btns.nth(i)
                try:
                    own = (b.inner_text() or "").strip()
                except (PlaywrightTimeoutError, PlaywrightError):
                    own = ""
                if own != "追加":
                    continue
                try:
                    ctx = b.evaluate(
                        "el => { let e=el; for(let i=0;i<6 && e && e.parentElement;"
                        " i++){ e=e.parentElement; const t=(e.innerText||'').trim();"
                        " if(t.length>4) return t; } return ''; }"
                    )
                except (PlaywrightTimeoutError, PlaywrightError):
                    ctx = ""
                if plan_name in (ctx or ""):
                    add_btn = b
                    break'''

assert src.count(OLD) == 1, f"expected 1 match, got {src.count(OLD)}"
T.write_text(src.replace(OLD, NEW), encoding="utf-8")
print("patched plan-button locator (button/a/role=button + exact own-text)")
