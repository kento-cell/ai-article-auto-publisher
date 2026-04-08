"""Republish the note intro article with auto-inserted stock images."""
from __future__ import annotations

import io
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from generators.image_sourcer import ImageSourcer
from publishers.note_publisher import NotePublisher

# Import main module as a fresh module (avoid its stdout side effects)
import importlib.util
_main_spec = importlib.util.spec_from_file_location("_main_mod", _ROOT / "main.py")
# Temporarily save stdout before loading main (which reassigns it)
_saved_stdout = sys.stdout
_saved_stderr = sys.stderr
_main_mod = importlib.util.module_from_spec(_main_spec)
_main_spec.loader.exec_module(_main_mod)
sys.stdout = _saved_stdout
sys.stderr = _saved_stderr
_insert_stock_images = _main_mod._insert_stock_images


def main() -> None:
    content = (_ROOT / "data/articles/note-ai-publisher-intro.md").read_text(
        encoding="utf-8"
    )
    title = "AIに記事を書かせてZennとnoteに自動投稿するシステムを作った話"

    sourcer = ImageSourcer()
    content_with_images = _insert_stock_images(
        content, title, sourcer, "note-ai-publisher-v2", section_count=3
    )
    print(f"Content length: {len(content)} -> {len(content_with_images)}")
    print(f"Image count: {content_with_images.count('![')}")

    (_ROOT / "data/articles/note-ai-publisher-v2.md").write_text(
        content_with_images, encoding="utf-8"
    )

    pub = NotePublisher(headless=False)
    try:
        url = pub.publish_article(
            title=title,
            content=content_with_images,
            tags=["AI", "Python", "自動化", "プログラミング", "LLM"],
            slug="note-ai-publisher-v2",
        )
        print(f"Published: {url}")
    finally:
        pub.close()


if __name__ == "__main__":
    main()
