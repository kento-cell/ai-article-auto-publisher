"""Dump the DOM around note's hashtag input on the publish-settings page
so we can find the correct "add" button / commit gesture."""
from __future__ import annotations
import os, sys, logging
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for ln in (_REPO/".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.startswith("#"):
        k,v = ln.split("=",1); os.environ.setdefault(k.strip(), v.strip())
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("inspect")
from publishers.note_publisher import NotePublisher

NOTE_KEY = "n444be2daa2ef"

pub = NotePublisher(headless=False)
try:
    pub._ensure_started()
    page = pub._page
    pub._assert_logged_in()
    page.goto(f"https://editor.note.com/notes/{NOTE_KEY}/edit/", wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(4000)
    page.locator("button:has-text('公開に進む')").first.click(timeout=8000)
    page.wait_for_timeout(5000)
    log.info("URL: %s", page.url)

    # Find tag input and dump the structure around it.
    tag_inp = page.locator("input[placeholder*='ハッシュタグ']").first
    tag_inp.wait_for(state="visible", timeout=8000)
    # Get the bounding section
    sect = tag_inp.evaluate("""el => {
        let p = el; for(let i=0;i<6;i++){ if(p.parentElement) p=p.parentElement; }
        return p.outerHTML.substring(0, 3000);
    }""")
    log.info("section HTML:\n%s", sect)

    # type one tag and see what the DOM shows
    tag_inp.click()
    page.wait_for_timeout(500)
    tag_inp.type("テストタグ", delay=30)
    page.wait_for_timeout(1000)
    snap1 = tag_inp.evaluate("""el => {
        let p = el; for(let i=0;i<6;i++){ if(p.parentElement) p=p.parentElement; }
        return p.outerHTML.substring(0, 3500);
    }""")
    log.info("AFTER TYPE:\n%s", snap1)
    # Look for + button / suggestion list near the input
    nearby_buttons = page.locator("button").all()
    for i, b in enumerate(nearby_buttons[:30]):
        try:
            t = (b.text_content() or "").strip()[:30]
            if t and any(k in t for k in ["追加","タグ","+","保存"]):
                log.info("  candidate button: %r", t)
        except: pass
    page.wait_for_timeout(2000)
finally:
    pub.close()
