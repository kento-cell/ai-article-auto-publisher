"""Try to find the delete/remove button on the eyecatch via various
selectors and hover states."""
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

        # Hover over eyecatch first
        box = page.evaluate(
            """() => {
                const img = document.querySelector('img[alt="eyecatch"]');
                if (!img) return null;
                const r = img.getBoundingClientRect();
                return {x: r.x + r.width/2, y: r.y + 40};
            }"""
        )
        page.mouse.move(box["x"], box["y"])
        page.wait_for_timeout(1500)

        # All clickable elements within 500px of the eyecatch
        info = page.evaluate(
            """() => {
                const img = document.querySelector('img[alt="eyecatch"]');
                const imgRect = img.getBoundingClientRect();
                const all = document.querySelectorAll('button, a, [role="button"], [onclick]');
                const near = [];
                for (const el of all) {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0) continue;
                    // Within 400px of eyecatch
                    if (Math.abs(r.top - imgRect.top) < 500 || Math.abs(r.bottom - imgRect.bottom) < 500) {
                        near.push({
                            tag: el.tagName,
                            label: el.getAttribute('aria-label') || '',
                            text: el.textContent.slice(0, 40).trim(),
                            title: el.getAttribute('title') || '',
                            class: (el.className || '').slice(0, 60),
                            x: Math.round(r.x),
                            y: Math.round(r.y),
                            w: Math.round(r.width),
                            h: Math.round(r.height),
                            visible: el.offsetParent !== null,
                        });
                    }
                }
                return near.slice(0, 60);
            }"""
        )
        import json
        for item in info:
            if item["visible"] and (item["label"] or item["text"] or item["title"]):
                print(f"{item['tag']:6s} [{item['x']:4},{item['y']:4}] label={item['label'][:30]!r} text={item['text'][:30]!r} title={item['title'][:20]!r}")

        time.sleep(12)
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
