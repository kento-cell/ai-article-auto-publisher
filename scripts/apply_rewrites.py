"""Apply rewritten note posts from data/rewrites/*.json to live note.com.

Each rewrite JSON has:
  - key: note post short key (the "n…" slug segment)
  - url: full post URL
  - new_title: replacement title
  - new_content: replacement body markdown
  - sources_verified: list (informational, not used at apply time)
  - rationale: string (informational)

Run:
    venv/Scripts/python.exe scripts/apply_rewrites.py
    py scripts/apply_rewrites.py --only n7221fde84d6a

Behaviour:
  - Strips any local ``![…](data/images/…)`` markdown from the rewrite
    body because we rely on note's native inline image rehost (see
    fix_recent_note_images.py).
  - Re-uploads 4 topical Unsplash images, distributed per-H2, so the
    rewritten article keeps the same visual density pattern as every
    other post.
  - Logs success/failure per post and exits non-zero if any fail.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from pathlib import Path

if sys.platform == "win32" and __name__ == "__main__":
    # Rewrap stdio for UTF-8 only when run as a script — importing as
    # a module (e.g. smoke tests) would otherwise crash on the prior
    # stdio being already closed by the outer harness.
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

for _line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        import os as _os
        _os.environ.setdefault(_k.strip(), _v.strip())

from publishers.note_publisher import NotePublisher  # noqa: E402
from scripts.fix_recent_note_images import (  # noqa: E402
    _download_topical_images,
    _strip_local_images_markdown,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("apply_rewrites")

_REWRITES_DIR = _REPO / "data" / "rewrites"


def _load_rewrites(only: str | None) -> list[dict]:
    items: list[dict] = []
    for p in sorted(_REWRITES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Skip %s (bad json): %s", p.name, exc)
            continue
        if only and data.get("key") != only:
            continue
        items.append({"path": p, **data})
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        help="Apply only the rewrite whose key matches this value.",
    )
    args = parser.parse_args()

    rewrites = _load_rewrites(args.only)
    if not rewrites:
        logger.error("No rewrites found in %s (filter=%r)", _REWRITES_DIR, args.only)
        return 1

    logger.info("Applying %d rewrite(s)", len(rewrites))
    for r in rewrites:
        logger.info(
            "  - %s → %s", r["key"], r["new_title"][:60],
        )

    pub = NotePublisher(headless=False)
    failures: list[str] = []
    try:
        for r in rewrites:
            url = r["url"]
            new_title = r["new_title"]
            new_content = _strip_local_images_markdown(r["new_content"])
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", r["key"])[:40]
            imgs = _download_topical_images(
                new_title, new_content, slug=f"rw_{slug}", count=4,
            )
            logger.info(
                "Editing %s  (title=%s, images=%d)",
                url, new_title[:40], len(imgs),
            )
            try:
                ok = pub.edit_article(
                    url=url,
                    new_title=new_title,
                    new_content=new_content,
                    inline_image_paths=[str(p.resolve()) for p in imgs] or None,
                )
            except Exception as exc:
                logger.error("edit_article raised: %s", exc)
                ok = False
            if not ok:
                failures.append(url)
    finally:
        pub.close()

    if failures:
        logger.error("Failures: %s", failures)
        return 1
    logger.info("All %d rewrite(s) applied.", len(rewrites))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
