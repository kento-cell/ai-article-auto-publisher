"""Strip hallucinated stock images from already-published note posts.

Background — 2026-04-30
=======================

Investigation showed that all 16 currently-published note articles
contain inline stock photos that have nothing to do with the article
subject. The worst offenders were:

* "休息の7分類" (rest framework) → photos of tombstones literally
  reading "At Rest"
* "東京のスペシャルティロースター5店" (coffee roasters) → sewing
  machines and electric kettles
* "非エンジニアがClaude Code" → women holding their heads / a boat
* "行動科学/朝活" (morning routines) → toothbrushes
* "タイムブロッキング/ポモドーロ" → concert stage lights

Root cause was in `_extract_image_query` (now patched) — keyword
extraction was first-match wins, so K-beauty articles matched on 韓国
and pulled Seoul cityscapes, "rest" articles matched the English
"at rest" tombstone idiom, etc.

This one-shot remediation walks each affected article's stored JSON,
strips every `![](data/images/stock/...)` block from the body
(leaving the cover image, which is a generated gradient and is
accurate), then calls `NotePublisher.edit_article` to overwrite the
live post with the cleaned content. Title, tags, paywall, hashtags
are preserved.

Usage::

    python scripts/fix_hallucinated_images.py            # dry run
    python scripts/fix_hallucinated_images.py --apply    # actually edit
    python scripts/fix_hallucinated_images.py --apply --only "休息"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load .env so NotePublisher can find profile_dir / credentials.
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
logger = logging.getLogger("fix_hallucinated_images")

# Match `![alt](data/images/stock/... "remote_url")` plus a leading or
# trailing blank line so the article body doesn't end up with stranded
# blank rows where images used to be.
_STOCK_IMG_RE = re.compile(
    r"\n*!\[[^\]]*\]\(\s*\.?/?(?:data|docs)/images/[^)]+\)\s*\n*",
)


def strip_inline_images(content: str) -> tuple[str, int]:
    """Remove every local stock-image markdown block from `content`.

    Returns (new_content, count_removed).
    """
    matches = _STOCK_IMG_RE.findall(content)
    cleaned = _STOCK_IMG_RE.sub("\n\n", content)
    # Collapse runs of >2 blank lines.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"
    return cleaned, len(matches)


def collect_affected() -> list[tuple[Path, dict]]:
    """Return [(json_path, parsed)] for every published note article
    whose body still contains local stock-image markdown."""
    out: list[tuple[Path, dict]] = []
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
        body = data.get("content", "") or ""
        if "data/images/" not in body and "docs/images/" not in body:
            continue
        out.append((f, data))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually edit live note posts. Without this flag the script "
        "only prints what it would do.",
    )
    ap.add_argument(
        "--only",
        help="Process only articles whose title contains this substring "
        "(useful for testing one fix before bulk-running).",
    )
    args = ap.parse_args()

    affected = collect_affected()
    if args.only:
        affected = [t for t in affected if args.only in t[1].get("title", "")]
    logger.info("Affected published note articles: %d", len(affected))
    for f, data in affected:
        title = data.get("title", "")
        url = (
            data.get("note_url")
            or data.get("published_url")
            or data.get("url")
        )
        body = data.get("content", "") or ""
        cleaned, removed = strip_inline_images(body)
        logger.info(
            "  %s  →  %d image(s) to remove",
            title[:70],
            removed,
        )
        if not args.apply:
            continue
        if removed == 0:
            continue
        # Persist the cleaned body back to the JSON store so future
        # republishes don't reintroduce the bad images. Keep a backup
        # of the original body for emergency rollback.
        data.setdefault("_original_content_with_bad_images", body)
        data["content"] = cleaned
        f.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if not args.apply:
        logger.info("Dry run. Re-run with --apply to write changes.")
        return 0

    # Live edit phase. Lazy-import to avoid Selenium/Playwright cost
    # during dry run.
    from publishers.note_publisher import NotePublisher  # noqa: E402

    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[tuple[str, str]] = []
    try:
        for f, data in affected:
            title = data.get("title", "")
            url = (
                data.get("note_url")
                or data.get("published_url")
                or data.get("url")
            )
            cleaned = data.get("content", "")
            if not url or not cleaned:
                continue
            logger.info("Editing live: %s", url)
            try:
                ok = pub.edit_article(
                    url=url,
                    new_title=title,
                    new_content=cleaned,
                )
            except Exception as exc:
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("  ✅ %s", title[:70])
            else:
                failed.append((title, url))
                logger.error("  ❌ %s", title[:70])
    finally:
        pub.close()

    logger.info("DONE — succeeded=%d failed=%d", succeeded, len(failed))
    for t, u in failed:
        logger.error("  failed: %s — %s", t[:70], u)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
