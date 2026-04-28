"""Open the publish settings panel and look for a cover image control."""
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
        page.wait_for_timeout(1000)

        # Click 公開に進む
        try:
            btn = page.locator("button:has-text('公開に進む')").first
            if btn.is_visible(timeout=3000):
                btn.click()
                print("clicked 公開に進む")
        except Exception as exc:
            print(f"couldn't click 公開に進む: {exc}")
            # Try alternative: 更新
            try:
                btn = page.locator("button:has-text('更新する')").first
                btn.click()
                print("clicked 更新する")
            except Exception as exc2:
                print(f"couldn't click 更新する either: {exc2}")

        page.wait_for_timeout(3000)

        # Dump what's visible now
        info = page.evaluate(
            """() => ({
                fileInputs: Array.from(document.querySelectorAll('input[type="file"]'))
                    .map(i => ({
                        accept: i.accept,
                        name: i.name,
                        id: i.id,
                        visible: i.offsetParent !== null,
                    })),
                buttons: Array.from(document.querySelectorAll('button[aria-label], button'))
                    .filter(b => b.offsetParent !== null && (b.getAttribute('aria-label') || b.textContent.trim().length > 0) && b.textContent.length < 40)
                    .map(b => b.getAttribute('aria-label') || b.textContent.trim())
                    .slice(0, 50),
                headings: Array.from(document.querySelectorAll('h1, h2, h3, h4, label'))
                    .filter(h => h.textContent.trim().length > 0 && h.textContent.length < 50)
                    .map(h => h.textContent.trim())
                    .slice(0, 20),
            })"""
        )
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2))

        time.sleep(12)
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
