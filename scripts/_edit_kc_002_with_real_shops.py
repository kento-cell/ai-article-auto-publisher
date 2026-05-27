"""Replace the body of note article n40b6f0a288b8 with a verified-shop
rewrite that names six real Korean cafes (with official Instagram URLs and
borrowed-image attribution).

Why a script: the existing publish was title-fulfilment-failed (talked about
"individual cafes" but named zero), and the new rewrite carries borrowed
official-Instagram references that need the price=¥0 invariant. NotePublisher
.edit_article keeps the existing URL so subscribers / shares still work.

The rewrite content lives in scripts/_kc_002_rewrite.md (canonical source).

Run:
    py scripts/_edit_kc_002_with_real_shops.py
"""
from __future__ import annotations

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("edit_kc_002")


ARTICLE_URL = "https://note.com/note-user/n/n40b6f0a288b8"
NEW_BODY_PATH = _REPO / "scripts" / "_kc_002_rewrite.md"


def main() -> int:
    body = NEW_BODY_PATH.read_text(encoding="utf-8")
    # The H1 line is "【保存版】…"; note treats the first line as title.
    lines = body.splitlines()
    if not lines:
        logger.error("empty body")
        return 1
    new_title = lines[0].strip()
    new_body = "\n".join(lines[2:]).strip()  # skip H1 + blank line
    logger.info("new title: %s", new_title)
    logger.info("new body: %d chars", len(new_body))

    # Sanity: borrowed-image marker must be present (we want the
    # publish-side guard to kick in if this ever re-runs through the
    # paid flow).
    from main import _has_borrowed_image_attribution
    borrowed, marker = _has_borrowed_image_attribution(new_body)
    if not borrowed:
        logger.error(
            "expected '画像をお借りしました' attribution in rewrite — aborting"
        )
        return 1
    logger.info("borrowed-image marker confirmed: %r", marker)

    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    try:
        ok = pub.edit_article(
            url=ARTICLE_URL,
            new_title=new_title,
            new_content=new_body,
            inline_image_paths=None,  # no local images — Instagram embeds only
            cover_image_path=None,  # keep existing cover
        )
    finally:
        pub.close()
    logger.info("edit_article returned: %s", ok)
    # Known issue (CLAUDE.md): edit_article sometimes returns False even
    # when note saved the edit. Verify with og:image / live page check
    # after the fact rather than trusting the bool.
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
