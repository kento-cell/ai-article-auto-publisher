"""Delete 2 existing AI note articles and re-publish upgraded v2
content with the pre-built titled thumbnails.

Run:
    py -X utf8 scripts/replace_ai_articles.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32" and __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("replace_ai_articles")

from publishers.note_publisher import NotePublisher  # noqa: E402


_TARGETS: list[dict] = [
    {
        "old_url": "https://note.com/note-user/n/na1defe84b0a0",
        "new_spec": "data/custom_posts/ai_gemini_shinsho_v2.json",
    },
    {
        "old_url": "https://note.com/note-user/n/nf6b8a333cf19",
        "new_spec": "data/custom_posts/ai_railway_shinsho_v2.json",
    },
]


def _delete_one(pub: NotePublisher, url: str) -> bool:
    logger.info("Deleting old article: %s", url)
    try:
        ok = pub.delete_article(url)
    except Exception as exc:
        logger.error("Delete raised: %s", exc)
        return False
    if ok:
        logger.info("  deleted OK")
    else:
        logger.error("  delete returned False")
    return ok


def _publish_one(spec_path: str) -> int:
    logger.info("Publishing upgraded version: %s", spec_path)
    cmd = [
        sys.executable, "-X", "utf8",
        str(_REPO / "scripts" / "publish_custom_post.py"),
        str(_REPO / spec_path),
    ]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        rc = subprocess.call(cmd, env=env)
    except Exception as exc:
        logger.error("publish_custom_post raised: %s", exc)
        return 1
    return rc


def main() -> int:
    pub = NotePublisher(headless=False)
    deleted: list[str] = []
    try:
        for t in _TARGETS:
            if _delete_one(pub, t["old_url"]):
                deleted.append(t["old_url"])
            # Spacing between deletes to avoid UI fights
            time.sleep(3)
    finally:
        pub.close()

    if len(deleted) != len(_TARGETS):
        logger.warning(
            "Only %d/%d deletes succeeded — skipping publish to avoid dupes",
            len(deleted), len(_TARGETS),
        )
        return 1

    # Sleep so note's dashboard fully reflects deletions before we
    # start posting new articles from the same account.
    time.sleep(5)

    fail = 0
    for t in _TARGETS:
        rc = _publish_one(t["new_spec"])
        if rc != 0:
            fail += 1
        time.sleep(3)

    logger.info("Done. failures=%d", fail)
    return fail


if __name__ == "__main__":
    raise SystemExit(main())
