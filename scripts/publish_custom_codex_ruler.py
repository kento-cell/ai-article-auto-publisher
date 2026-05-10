"""Publish the custom Codex/ruler/Claude Code article (2026-05-07).

Pulls the markdown body from `data/articles/_drafts/custom_codex_ruler_20260507.md`
and pushes it through the production note flow (ChatGPT cover + Selenium
editor) using `main._publish_note`. Free-tier (price=0).

Brave must be CLOSED for ChatGPT image gen to succeed. If it's running,
the helper falls back to Unsplash automatically.
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
logger = logging.getLogger("publish_custom_codex_ruler")

DRAFT_PATH = _REPO / "data" / "articles" / "_drafts" / "custom_codex_ruler_20260507.md"
TITLE = (
    "Cursor / Claude Code 民へ告ぐ。4/16 の Codex 大型UPDで地殻変動した話と、"
    "30種類のAIに1ファイルでルール配布する .ruler 完全ガイド"
)
SOURCE = (
    "OpenAI Codex (4/16 update), Anthropic Claude Opus 4.7, "
    "intellectronica/ruler v0.3.40, AGENTS.md (AAIF)"
)


def _build_article_record(content: str) -> dict:
    return {
        "title": TITLE,
        "content": content,
        "platform": "note",
        "source": SOURCE,
        "scores": {
            "overall_grade": "A",
            "evidence_grade": "A",
            "numeric_score": 92.0,
        },
        "structure": "feature_long_form",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_custom_authored": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply", action="store_true",
        help="Actually publish; without this flag, dry-run only.",
    )
    args = ap.parse_args()

    if not DRAFT_PATH.exists():
        logger.error("draft markdown not found: %s", DRAFT_PATH)
        return 2

    content = DRAFT_PATH.read_text(encoding="utf-8")
    logger.info(
        "draft loaded: %s (%d chars)", DRAFT_PATH.name, len(content),
    )
    logger.info("title: %s", TITLE)

    if not args.apply:
        logger.info("dry-run — pass --apply to publish")
        # Persist a dry-run record so it's discoverable.
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = _REPO / "data" / "articles" / f"note-CUSTOM-{ts}.json"
        rec = _build_article_record(content)
        out_path.write_text(
            json.dumps(rec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("dry-run record saved: %s", out_path)
        return 0

    # Persist the article record FIRST so we have a JSON to reference.
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = _REPO / "data" / "articles" / f"note-CUSTOM-{ts}.json"
    record = _build_article_record(content)
    out_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("record saved: %s", out_path)

    config_path = _REPO / "config" / "settings.yaml"
    config: dict = {}
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning(
                "settings.yaml unreadable (%s) — proceeding empty", exc,
            )

    from main import _publish_note  # noqa: E402

    logger.info("starting note publish (price=0, free tier)")
    url = None
    try:
        url = _publish_note(
            title=TITLE,
            content=content,
            config=config,
            source=SOURCE,
            price=0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("_publish_note raised: %s", exc)
        return 3

    if not url:
        logger.error("publish returned None — see note publisher logs")
        return 4

    record["published_url"] = url
    record["published_at"] = datetime.now(timezone.utc).isoformat()
    out_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("PUBLISHED: %s", url)

    # Notify via Slack so the user gets a ping when it lands.
    try:
        import requests
        webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if webhook:
            requests.post(
                webhook,
                json={
                    "text": f":sparkles: 特注記事を note に公開しました\n*{TITLE}*\n{url}",
                },
                timeout=10,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Slack notify failed: %s", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
