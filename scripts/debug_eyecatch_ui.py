"""Open one note article editor and dump the DOM around the eyecatch
area so we can see what selectors actually exist. One-shot debug tool.
"""
import io
import os
import sys
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
        m = re.search(r"/n/([a-zA-Z0-9]+)", URL)
        note_id = m.group(1)
        edit_url = f"https://editor.note.com/notes/{note_id}/edit/"
        page.goto(edit_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)
        page.wait_for_selector(".ProseMirror", timeout=20000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)

        info = page.evaluate(
            """() => {
                const result = {};
                result.fileInputs = Array.from(
                    document.querySelectorAll('input[type="file"]')
                ).map(i => ({
                    accept: i.accept,
                    name: i.name,
                    id: i.id,
                    visible: i.offsetParent !== null,
                    outerHTML: i.outerHTML.slice(0, 200),
                }));
                result.addImageButtons = Array.from(
                    document.querySelectorAll(
                        '[aria-label*="画像"], button[aria-label*="変更"], button[aria-label*="編集"]'
                    )
                ).map(b => ({
                    ariaLabel: b.getAttribute('aria-label'),
                    text: b.textContent.slice(0, 40),
                    tag: b.tagName,
                }));
                result.eyecatchImg = Array.from(
                    document.querySelectorAll('img')
                ).slice(0, 3).map(i => ({
                    src: i.src.slice(0, 80),
                    alt: i.alt,
                    className: i.className,
                }));
                return result;
            }"""
        )
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2))
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
