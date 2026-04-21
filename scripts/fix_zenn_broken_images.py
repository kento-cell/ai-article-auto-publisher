"""Repair Zenn articles whose inline images reference ``data/images/stock/...``.

Those paths don't exist in the Zenn content repo, so Zenn's renderer
serves ``error.svg`` for each image. External image URLs are rejected
by Zenn too (confirmed empirically 2026-04-20), so the only fix is to
commit the actual image binaries to ``<zenn_repo>/images/<slug>/`` and
rewrite markdown to ``/images/<slug>/<basename>``.

The script:
  1. Walks every ``*.md`` under ``$ZENN_REPO_PATH/articles``.
  2. For each file with ``data/images/stock/`` references, calls
     :meth:`ZennPublisher._localize_stock_images_for_zenn` — it
     downloads the title-attribute Unsplash URL into
     ``$ZENN_REPO_PATH/images/<slug>/`` and rewrites markdown.
  3. Stages the md + images dir, commits, pushes.

Run:
    venv/Scripts/python.exe scripts/fix_zenn_broken_images.py
"""

from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32" and __name__ == "__main__":
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
        os.environ.setdefault(_k.strip(), _v.strip())

from publishers.zenn_publisher import ZennPublisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fix_zenn_broken_images")


def main() -> int:
    zenn_repo_env = os.environ.get("ZENN_REPO_PATH")
    if not zenn_repo_env:
        logger.error("ZENN_REPO_PATH is not set in .env")
        return 1
    articles_dir = Path(zenn_repo_env) / "articles"
    if not articles_dir.exists():
        logger.error("articles dir not found: %s", articles_dir)
        return 1

    pub = ZennPublisher(zenn_repo_env)

    touched_md: list[Path] = []
    touched_image_dirs: list[Path] = []
    for md in sorted(articles_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        if "data/images/stock/" not in text:
            continue
        slug = md.stem
        logger.info("processing %s", md.name)
        new_text = pub._localize_stock_images_for_zenn(text, slug)
        if new_text == text:
            logger.warning("no change produced for %s", md.name)
            continue
        md.write_text(new_text, encoding="utf-8")
        touched_md.append(md)
        img_dir = Path(zenn_repo_env) / "images" / slug
        if img_dir.exists():
            touched_image_dirs.append(img_dir)

    if not touched_md:
        logger.info("Nothing to repair.")
        return 0

    logger.info(
        "Rewrote %d md file(s); %d image dir(s) to stage. Pushing.",
        len(touched_md), len(touched_image_dirs),
    )
    try:
        for md in touched_md:
            pub._run_git("add", str(md))
        for d in touched_image_dirs:
            pub._run_git("add", str(d))
        pub._run_git(
            "commit", "-m",
            f"fix(images): localise Unsplash photos into images/<slug>/ ({len(touched_md)} articles)",
        )
        pub._run_git("push")
    except Exception as exc:
        logger.exception("git push failed: %s", exc)
        return 1

    logger.info("Done — %d article(s) repaired.", len(touched_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
