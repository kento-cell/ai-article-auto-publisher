"""Publish the top-scoring unpublished note articles.

Symmetric counterpart of `publish_top_zenn_articles.py` but for the
note platform. note has no equivalent of Zenn's silent cap, so this
just runs the standard `main._publish_note` flow (ChatGPT Ghibli
cover + Selenium-driven note editor).

Selection rules:
  * Only `data/articles/note-*.json` entries with no published_url.
  * Sorted by `scores.numeric_score` desc.
  * Skip "thin" articles whose title is shorter than `--min-title-len`
    (Google-Trends-driven single-keyword pieces — `南海電鉄`,
    `はしか 予防接種` etc — that scored well on objective grading
    but read like stub content).

Usage::

    python scripts/publish_top_note_articles.py
    python scripts/publish_top_note_articles.py --apply -n 3
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import yaml
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
logger = logging.getLogger("publish_top_note")


def _score(d: dict) -> float:
    s = d.get("scores", {}) or {}
    raw = s.get("numeric_score")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_published(d: dict) -> bool:
    return bool(
        d.get("published_url") or d.get("note_url") or d.get("url"),
    )


def collect_candidates(
    top_n: int, min_title_len: int,
) -> list[tuple[Path, dict, float]]:
    out: list[tuple[Path, dict, float]] = []
    for f in (_REPO / "data" / "articles").glob("note-*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("skip %s: %s", f.name, exc)
            continue
        if _is_published(d):
            continue
        title = d.get("title", "") or ""
        # Skip Google-Trends stubs (single-keyword titles).
        if len(title) < min_title_len:
            continue
        out.append((f, d, _score(d)))
    out.sort(key=lambda t: t[2], reverse=True)
    return out[:top_n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually publish; without this flag dry-run only.")
    ap.add_argument("-n", "--top-n", type=int, default=3,
                    help="How many high-scoring articles to publish.")
    ap.add_argument("--min-title-len", type=int, default=20,
                    help="Skip thin trends-stub titles shorter than this.")
    args = ap.parse_args()

    candidates = collect_candidates(args.top_n, args.min_title_len)
    logger.info("top %d candidates (title >= %d chars):",
                len(candidates), args.min_title_len)
    for f, d, s in candidates:
        og = (d.get("scores", {}) or {}).get("overall_grade", "?")
        logger.info("  [score=%.1f grade=%s] %s",
                    s, og, d.get("title", "")[:70])

    if not args.apply:
        logger.info("dry run — pass --apply to publish")
        return 0

    # Reuse main.py's helper so we get exactly the production flow:
    # ChatGPT Ghibli cover via chatgpt_batch_helper, Selenium-driven
    # note editor, NotePublisher.publish_article with the validated
    # cover_image_path / inline images.
    from main import _publish_note  # noqa: E402

    config_path = _REPO / "config" / "settings.yaml"
    config: dict = {}
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("settings.yaml unreadable (%s) — proceeding empty", exc)

    succeeded = 0
    failed: list[tuple[str, str]] = []
    for f, d, s in candidates:
        title = d.get("title", "")
        content = d.get("content", "") or ""
        source = str(d.get("source", ""))
        if not title or not content:
            logger.warning("skip %s: missing title/content", f.name)
            continue
        logger.info("publishing: %s (score=%.1f)", title[:70], s)
        url: str | None = None
        try:
            url = _publish_note(
                title=title,
                content=content,
                config=config,
                source=source,
                price=0,
            )
        except Exception as exc:
            logger.exception("_publish_note raised: %s", exc)
            url = None
        if not url:
            failed.append((title, "publish returned None"))
            logger.error("FAIL: %s", title[:70])
            # Don't auto-stop on failure — note has no platform cap;
            # next attempt is independent.
            continue
        succeeded += 1
        d["published_url"] = url
        d["published_at"] = datetime.now(timezone.utc).isoformat()
        f.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("OK %s → %s", title[:70], url)

    logger.info(
        "DONE — succeeded=%d failed=%d", succeeded, len(failed),
    )
    for t, reason in failed:
        logger.warning("  failed: %s — %s", t[:70], reason)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
