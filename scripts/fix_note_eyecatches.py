"""Replace hallucinated eyecatch (thumbnail) images on already-published note posts.

Background — 2026-05-01
=======================

`fix_hallucinated_images.py` (run on 2026-04-30) stripped the bad
inline stock photos from 16 published note posts. That script,
however, only edited the article body — it did NOT touch the
eyecatch (note's per-article thumbnail).

When the user opened the K-beauty article (nd0cb235da4a6) on
2026-05-01, the live thumbnail still showed an unrelated image:
"ローカル開発環境を爆速化させる — Model Context Protocol (MCP)".
The local cover_image on disk is the correct dark-navy K-beauty
gradient; the wrong one was uploaded by note.com during the
original Selenium-driven publish.

This script walks each affected JSON, resolves cover_image to an
absolute path, and calls NotePublisher.edit_article with
cover_image_path set, which uses force_replace=True to swap the
eyecatch.

Usage::

    python scripts/fix_note_eyecatches.py                # dry run
    python scripts/fix_note_eyecatches.py --apply        # actually edit
    python scripts/fix_note_eyecatches.py --apply --only "肌質"
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fix_note_eyecatches")


def _resolve_cover(raw: str | None) -> Path | None:
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = _REPO / p
    return p if p.exists() else None


def collect_targets(only: str | None) -> list[tuple[Path, dict, Path]]:
    """Find every published note article that has a usable local cover
    image on disk. Returns (json_path, parsed, abs_cover_path)."""
    out: list[tuple[Path, dict, Path]] = []
    for f in sorted(
        (_REPO / "data" / "articles").glob("note-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("skip %s: %s", f.name, exc)
            continue
        url = (
            data.get("note_url")
            or data.get("published_url")
            or data.get("url")
            or ""
        )
        if not url:
            continue
        if only and only not in data.get("title", ""):
            continue
        cover = _resolve_cover(data.get("cover_image"))
        if not cover:
            logger.warning(
                "skip (no cover on disk): %s",
                data.get("title", "")[:60],
            )
            continue
        out.append((f, data, cover))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="title substring filter")
    args = ap.parse_args()

    targets = collect_targets(args.only)
    logger.info("targets: %d", len(targets))
    for f, data, cover in targets:
        logger.info("  %s", data.get("title", "")[:70])
        logger.info("     url:   %s", data.get("published_url"))
        logger.info("     cover: %s", cover)

    if not args.apply:
        logger.info("dry run — pass --apply to upload")
        return 0

    from publishers.note_publisher import NotePublisher  # noqa: E402

    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[tuple[str, str]] = []
    try:
        for f, data, cover in targets:
            title = data.get("title", "")
            url = data.get("note_url") or data.get("published_url") or data.get("url")
            content = data.get("content", "") or ""
            if not url:
                continue
            logger.info("editing eyecatch: %s", url)
            try:
                ok = pub.edit_article(
                    url=url,
                    new_title=title,
                    new_content=content,
                    cover_image_path=str(cover),
                )
            except Exception as exc:
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("  OK %s", title[:70])
            else:
                failed.append((title, url))
                logger.error("  FAIL %s", title[:70])
    finally:
        pub.close()

    logger.info("DONE — succeeded=%d failed=%d", succeeded, len(failed))
    for t, u in failed:
        logger.error("  failed: %s — %s", t[:70], u)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
