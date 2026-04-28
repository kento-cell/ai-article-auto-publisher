"""Click the existing eyecatch and dump what DOM changes appear —
menu? modal? file input?"""
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
        page.wait_for_timeout(1000)

        # Snapshot baseline DOM
        before = page.evaluate("""() => document.body.innerHTML.length""")
        print(f"before click: body html len = {before}")

        # Click eyecatch
        clicked = page.evaluate(
            """() => {
                const img = document.querySelector('img[alt="eyecatch"]');
                if (!img) return 'no-img';
                img.scrollIntoView();
                const clickable = img.closest('button') || img.closest('[role="button"]') || img.parentElement;
                clickable.click();
                return 'clicked';
            }"""
        )
        print(f"click result: {clicked}")
        page.wait_for_timeout(1500)

        # Inspect what's new: buttons, file inputs, menus
        after = page.evaluate(
            """() => {
                return {
                    bodyLen: document.body.innerHTML.length,
                    fileInputs: document.querySelectorAll('input[type="file"]').length,
                    menus: Array.from(document.querySelectorAll('[role="menu"], [role="dialog"], .menu, .popover'))
                        .map(el => ({
                            role: el.getAttribute('role'),
                            text: el.textContent.slice(0, 100),
                        })),
                    newButtons: Array.from(document.querySelectorAll('button[aria-label]'))
                        .map(b => b.getAttribute('aria-label')).slice(0, 15),
                };
            }"""
        )
        import json
        print(json.dumps(after, ensure_ascii=False, indent=2))

        # Keep open for manual inspection
        time.sleep(15)
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
