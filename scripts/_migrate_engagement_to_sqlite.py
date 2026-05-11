"""One-shot migration: data/article_performance.jsonl -> SQLite.

The JSONL has 378 rows (2026-05-11). Each row is one snapshot of one
article's engagement at a measurement timestamp. We map to the
engagement_log table:

JSONL                        -> engagement_log
- key (note id slug)         -> article_id
- url                        -> url
- like_count                 -> likes
- comment_count              -> comments
- anonymous_like_count       -> (folded into likes via +0.5 weight)
- fetched_at                 -> measured_at
- (none)                     -> platform (= 'note', JSONL is note-only)

The script is idempotent: it checks for an existing
(article_id, measured_at) pair before insert. After successful
migration the JSONL is left in place — operator decides whether to
delete it manually.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.telemetry_db import init_db, connect  # noqa: E402

JSONL_PATH = _REPO / "data" / "article_performance.jsonl"


def main() -> int:
    if not JSONL_PATH.exists():
        print(f"NO JSONL at {JSONL_PATH}")
        return 0

    init_db()
    rows = JSONL_PATH.read_text(encoding="utf-8").splitlines()
    inserted = 0
    skipped = 0
    with connect() as conn:
        for line in rows:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            article_id = rec.get("key") or rec.get("url", "").split("/")[-1]
            url = rec.get("url", "")
            measured_at = rec.get("fetched_at", "")
            likes = int(rec.get("like_count", 0))
            comments = int(rec.get("comment_count", 0))
            anon_likes = int(rec.get("anonymous_like_count", 0))
            views = None  # not tracked in this JSONL
            # Skip duplicate (article_id, measured_at) pairs.
            existing = conn.execute(
                "SELECT 1 FROM engagement_log "
                "WHERE article_id=? AND measured_at=?",
                (article_id, measured_at),
            ).fetchone()
            if existing:
                skipped += 1
                continue
            # Fold anon likes into likes with weight 0.5 (matches the
            # legacy scoring formula in scripts/analyze_performance).
            blended_likes = int(likes + 0.5 * anon_likes)
            score = blended_likes + 0.5 * comments + 0.1 * (views or 0)
            conn.execute(
                "INSERT INTO engagement_log "
                "(article_id, platform, url, measured_at, likes, comments, views, engagement_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article_id, "note", url, measured_at,
                    blended_likes, comments, views, score,
                ),
            )
            inserted += 1
    print(f"DONE - inserted {inserted}, skipped (already present) {skipped}")
    print(f"telemetry DB: {_REPO / 'data' / 'telemetry.sqlite3'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
