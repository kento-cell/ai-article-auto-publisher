"""Scrape own-article performance metrics from note.com's public creator
API and persist them as a append-only JSONL.

Powers the self-improving quality loop added 2026-04-23. Without a live
view/like signal, ``experiment_variant`` and ``learn_adoption`` stored
on each article are stranded — we don't know which flag combinations
or learn-block patterns actually drove reader engagement. This scraper
closes that gap.

Cadence: intended to run daily (from ``--learn`` mode, but invokable
standalone). Idempotent — writing a record per (article_key, fetched_at)
so trends over time can be recovered if ever needed.

Output: ``data/article_performance.jsonl`` — each row ``{key, url,
title, publish_at, age_days, like_count, comment_count,
anonymous_like_count, image_count, is_limited, fetched_at}``.

API caveat: note's public endpoint does not expose view counts. Like
count + comment count are used as engagement proxies; comparative
analysis still works because we rank within our own article set.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

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
logger = logging.getLogger("scrape_note_performance")

_NOTE_USER = os.environ.get("NOTE_USER", "")
_OUT_PATH = _REPO / "data" / "article_performance.jsonl"
_API_BASE = f"https://note.com/api/v2/creators/{_NOTE_USER}/contents"


def _fetch_page(page: int) -> list[dict]:
    url = f"{_API_BASE}?kind=note&page={page}"
    req = Request(
        url, headers={"User-Agent": "Mozilla/5.0 perf-scraper"},
    )
    raw = urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    return (data.get("data") or {}).get("contents", []) or []


def _is_last_page(page_contents: list[dict], max_page: int) -> bool:
    # note's API returns empty contents at end-of-feed. Belt-and-braces
    # page cap prevents infinite loops on API quirks.
    return (not page_contents) or max_page >= 10


def _summarise(item: dict, now: datetime) -> dict:
    publish_at_raw = item.get("publishAt") or ""
    try:
        publish_at = datetime.fromisoformat(publish_at_raw)
        if publish_at.tzinfo is None:
            publish_at = publish_at.replace(tzinfo=timezone.utc)
        age_hours = (now - publish_at).total_seconds() / 3600
    except ValueError:
        age_hours = 0.0
    return {
        "key": item.get("key"),
        "url": item.get("noteUrl"),
        "title": item.get("name") or "",
        "publish_at": publish_at_raw,
        "age_hours": round(age_hours, 2),
        "age_days": round(age_hours / 24, 2),
        "like_count": item.get("likeCount") or 0,
        "comment_count": item.get("commentCount") or 0,
        "anonymous_like_count": item.get("anonymousLikeCount") or 0,
        "image_count": item.get("imageCount") or 0,
        "is_limited": bool(item.get("isLimited")),
        "status": item.get("status") or "",
        "fetched_at": now.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-pages", type=int, default=5,
        help="最大で何ページまで遡るか (1ページ≒6件、既定5=30件)",
    )
    args = parser.parse_args()

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    total = 0
    written = 0
    with open(_OUT_PATH, "a", encoding="utf-8") as f:
        for page in range(1, args.max_pages + 1):
            try:
                contents = _fetch_page(page)
            except Exception as exc:
                logger.warning("page %d fetch failed: %s", page, exc)
                break
            if _is_last_page(contents, page):
                if not contents:
                    break
            for item in contents:
                if item.get("status") != "published":
                    continue
                rec = _summarise(item, now)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                total += 1
                written += 1
            time.sleep(1.0)  # polite

    logger.info(
        "wrote %d performance rows → %s", written, _OUT_PATH,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
