"""Hover over the eyecatch and see what toolbar/buttons appear."""
import io
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
_ENV = _REPO / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from publishers.note_publisher import NotePublisher

URL = "https://note.com/note-user/n/na1defe84b0a0"


def main() -> int:
    pub = NotePublisher(headless=False)
    try:
        pub._ensure_started()
        page = pub._page
        pub._assert_logged_in()
        import re
        note_id = re.search(r"/n/([a-zA-Z0-9]+)", URL).group(1)
        page.goto(
            f"https://editor.note.com/notes/{note_id}/edit/",
            wait_until="networkidle",
            timeout=30000,
        )
        page.wait_for_timeout(5000)
        page.wait_for_selector(".ProseMirror", timeout=20000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)

        # Parent chain + ancestor data attributes of eyecatch img
        info = page.evaluate(
            """() => {
                const img = document.querySelector('img[alt="eyecatch"]');
                if (!img) return {error: 'no img'};
                let el = img;
                const chain = [];
                for (let i = 0; i < 8 && el; i++) {
                    chain.push({
                        tag: el.tagName,
                        class: (el.className || '').slice(0, 80),
                        attrs: Array.from(el.attributes || []).slice(0, 8).map(a => a.name + '=' + a.value.slice(0, 30)),
                    });
                    el = el.parentElement;
                }
                return {chain};
            }"""
        )
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2))

        # Hover over eyecatch
        box = page.evaluate(
            """() => {
                const img = document.querySelector('img[alt="eyecatch"]');
                if (!img) return null;
                const r = img.getBoundingClientRect();
                return {x: r.x + r.width/2, y: r.y + r.height/2, w: r.width, h: r.height};
            }"""
        )
        print("eyecatch box:", box)

        if box:
            page.mouse.move(box["x"], box["y"])
            page.wait_for_timeout(1500)

            after_hover = page.evaluate(
                """() => ({
                    buttons: Array.from(document.querySelectorAll('button'))
                        .filter(b => b.offsetParent !== null && b.textContent.length < 30)
                        .map(b => b.textContent.trim())
                        .filter(t => t)
                        .slice(0, 30),
                })"""
            )
            print("after hover:", json.dumps(after_hover, ensure_ascii=False, indent=2))

        time.sleep(10)
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
