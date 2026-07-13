"""One-shot emergency fix for 3 articles published 2026-07-13 with broken
content (mid-sentence truncation + internal knowledge_topic:// ID leakage).
Found by the new article-reviewer subagent's post-publish review.

Usage: py scripts/_fix_broken_articles_20260713.py <article_key>
  article_key: "kpop" | "makgeolli" | "camera"
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fix_broken_articles")

from publishers.note_publisher import NotePublisher

_REPO = Path(__file__).resolve().parent.parent

# PII policy: note handle comes from .env (NOTE_USER), never hardcoded
# in this public repo.
_NOTE_USER = os.environ.get("NOTE_USER", "")

_TARGETS = {
    "kpop": {
        "url": f"https://note.com/{_NOTE_USER}/n/n65306d782b03",
        "content_file": _REPO / "data" / "_fix_article1_content.txt",
        "make_free": False,  # already free
    },
    "makgeolli": {
        "url": f"https://note.com/{_NOTE_USER}/n/n660937d81cdd",
        "content_file": _REPO / "data" / "_fix_article3_content.txt",
        "make_free": True,  # was paid, downgrading to free
    },
    "camera": {
        "url": f"https://note.com/{_NOTE_USER}/n/n1ad6c673fc7b",
        "content_file": _REPO / "data" / "_fix_article4_content.txt",
        "make_free": True,  # was paid, downgrading to free
    },
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in _TARGETS:
        print(f"Usage: py {sys.argv[0]} <{'|'.join(_TARGETS.keys())}>")
        return 1
    key = sys.argv[1]
    target = _TARGETS[key]

    content = target["content_file"].read_text(encoding="utf-8")
    # First line is the title, rest is body (matches article JSON convention).
    lines = content.split("\n", 1)
    body = lines[1].lstrip("\n") if len(lines) > 1 else content

    logger.info("Fixing %s (%s) — make_free=%s, body=%d chars",
                key, target["url"], target["make_free"], len(body))

    pub = NotePublisher()
    try:
        ok = pub.edit_article(
            url=target["url"],
            new_content=body,
            make_free=target["make_free"],
        )
        logger.info("edit_article returned: %s", ok)
        return 0 if ok else 1
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
