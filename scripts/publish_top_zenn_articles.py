"""Publish the top-scoring unpublished Zenn articles as proper articles.

Background — 2026-05-01:
========================

Many high-scoring Zenn articles in `data/articles/` are sitting
unpublished (or were routed to Scraps under the older
`publish.zenn_scrap_only` experiment). The user wants them shipped
as articles, picking by `scores.numeric_score` desc, multiple at a
time.

This script:
  1. Scans data/articles/zenn-*.json for entries with no
     published_url.
  2. Sorts by numeric_score descending.
  3. For each top-N candidate, calls `_publish_zenn` (the same code
     path that main.py --publish uses), writes the resulting URL
     back into the JSON, and stops the batch the moment a Zenn 404
     is detected (cap exhausted).

Usage::

    python scripts/publish_top_zenn_articles.py --dry-run
    python scripts/publish_top_zenn_articles.py --apply -n 5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
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
logger = logging.getLogger("publish_top_zenn")


def _score(d: dict) -> float:
    s = d.get("scores", {}) or {}
    raw = s.get("numeric_score")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_published(d: dict) -> bool:
    return bool(
        d.get("published_url")
        or d.get("zenn_url")
        or d.get("url"),
    )


def collect_candidates(top_n: int) -> list[tuple[Path, dict, float]]:
    out: list[tuple[Path, dict, float]] = []
    for f in (_REPO / "data" / "articles").glob("zenn-*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("skip %s: %s", f.name, exc)
            continue
        if _is_published(d):
            continue
        out.append((f, d, _score(d)))
    out.sort(key=lambda t: t[2], reverse=True)
    return out[:top_n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually publish; without this flag dry-run only.")
    ap.add_argument("-n", "--top-n", type=int, default=5,
                    help="How many high-scoring articles to publish.")
    args = ap.parse_args()

    candidates = collect_candidates(args.top_n)
    logger.info("top %d unpublished candidates:", len(candidates))
    for f, d, s in candidates:
        title = d.get("title", "")[:60]
        og = (d.get("scores", {}) or {}).get("overall_grade", "?")
        logger.info("  [score=%.1f grade=%s] %s", s, og, title)

    if not args.apply:
        logger.info("dry run — pass --apply to publish")
        return 0

    if not os.environ.get("ZENN_REPO_PATH"):
        logger.error("ZENN_REPO_PATH not set in env — abort")
        return 1

    # Pre-flight: detect the 2026-04-15+ Zenn article cap. If the most
    # recent push from `git log` already 404s on zenn.dev, every new
    # push will too, and we'd just be polluting the zenn-content repo
    # with .md files that will never surface. Abort instead. The user
    # has to investigate on zenn.dev/dashboard before this can be
    # un-stuck — see memory/project_zenn_cap_blocked.md.
    try:
        import subprocess
        import urllib.request
        zenn_user = os.environ.get("ZENN_USERNAME", "zenn-user")
        # Pick the most recent published commit slug.
        out = subprocess.check_output(
            [
                "git", "-C", os.environ["ZENN_REPO_PATH"],
                "log", "--oneline", "-1", "--grep=publish:",
            ],
            text=True, errors="replace",
        )
        if out.strip():
            last_line = out.strip().splitlines()[0]
            # "abc123 publish: 20260501-foo-bar"
            parts = last_line.split("publish:", 1)
            if len(parts) == 2:
                last_slug = parts[1].strip()
                check_url = (
                    f"https://zenn.dev/{zenn_user}/articles/{last_slug}"
                )
                req = urllib.request.Request(
                    check_url, method="HEAD",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        status = resp.status
                except urllib.error.HTTPError as exc:
                    status = exc.code
                except Exception:
                    status = None
                if status == 404:
                    logger.error(
                        "Zenn cap detection: most recent push %s "
                        "is HTTP 404 — additional pushes will be "
                        "silently dropped too. Aborting before we "
                        "pollute the zenn-content repo.",
                        check_url,
                    )
                    logger.error(
                        "Investigate zenn.dev/dashboard before "
                        "re-running this script. See "
                        "memory/project_zenn_cap_blocked.md.",
                    )
                    return 3
                if status:
                    logger.info(
                        "Zenn cap probe OK: last push %s → HTTP %s",
                        check_url, status,
                    )
    except Exception as exc:
        logger.warning(
            "cap pre-flight failed (continuing): %s", exc,
        )

    # Reuse main.py's exact publish helper so behaviour matches the
    # standard --publish path (404 detection, slug generation, image
    # localisation under articles/<slug>/, etc).
    from main import _publish_zenn, _is_zenn_article_404  # noqa: E402

    succeeded = 0
    failed: list[tuple[str, str]] = []
    cap_hit = False
    for f, d, s in candidates:
        if cap_hit:
            logger.info(
                "skip remaining: Zenn cap was already exhausted in this batch",
            )
            break
        article_id = d.get("article_id") or f.stem
        title = d.get("title", "")
        content = d.get("content", "") or ""
        if not title or not content:
            logger.warning("skip %s: missing title or content", f.name)
            continue
        logger.info("publishing: %s (score=%.1f)", title[:60], s)
        url: str | None = None
        try:
            url = _publish_zenn(article_id, title, content, d)
        except Exception as exc:
            logger.exception("_publish_zenn raised: %s", exc)
            url = None
        if not url:
            failed.append((title, "publish returned None"))
            cap_hit = True
            logger.warning("publish failed → flagging cap exhausted")
            continue
        if _is_zenn_article_404(url):
            failed.append((title, f"404 at {url}"))
            cap_hit = True
            logger.warning("404 detected at %s → cap likely full", url)
            continue
        succeeded += 1
        # Persist the URL into the JSON so the next run skips this one
        # and main.py treats it as published.
        d["published_url"] = url
        d["published_at"] = datetime.now(timezone.utc).isoformat()
        f.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("OK %s → %s", title[:60], url)

    logger.info(
        "DONE — succeeded=%d failed=%d cap_hit=%s",
        succeeded, len(failed), cap_hit,
    )
    for t, reason in failed:
        logger.warning("  failed: %s — %s", t[:60], reason)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
