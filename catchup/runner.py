"""Catchup pipeline: fetch → dedup → cap → summarise → post Slack.

Entry point used by both the CLI script (`scripts/run_catchup.py`) and
the Slack bot's `catchup` command.
"""
from __future__ import annotations

import logging
import os

from publishers.slack_notifier import SlackNotifier

from .dedup import Dedup
from .digest import build
from .sources import fetch_all
from .summarizer import summarize

logger = logging.getLogger(__name__)

# Hard ceiling on items we send to Gemma3 — protects against a feed
# explosion (e.g. arXiv RSS dropping 200 papers at midnight UTC).
_MAX_TO_SUMMARISE = 18


def _cap(items: list[dict]) -> list[dict]:
    """Take Tier1 first, then 2, then 3, until we hit _MAX_TO_SUMMARISE."""
    by_tier = {1: [], 2: [], 3: []}
    for it in items:
        by_tier.setdefault(it.get("tier", 3), []).append(it)
    for t in by_tier:
        by_tier[t].sort(
            key=lambda it: it.get("published_at") or 0, reverse=True
        )
    out: list[dict] = []
    for t in (1, 2, 3):
        for it in by_tier.get(t, []):
            if len(out) >= _MAX_TO_SUMMARISE:
                return out
            out.append(it)
    return out


def run(dry_run: bool = False) -> dict:
    """Execute the full catchup. Returns a small stats dict.

    Args:
        dry_run: If True, skip Slack post and skip marking items as sent.
    """
    logger.info("catchup: fetching sources...")
    raw = fetch_all()
    logger.info("catchup: %d raw items fetched", len(raw))

    dedup = Dedup()
    try:
        new = dedup.filter_new(raw)
        logger.info("catchup: %d new items after dedup", len(new))

        capped = _cap(new)
        logger.info("catchup: %d items will be summarised", len(capped))

        summarize(capped)

        msg = build(capped)
        if dry_run:
            logger.info("dry_run: skipping slack post")
            print(msg)
            return {"fetched": len(raw), "new": len(new), "sent": 0}

        catchup_webhook = (
            os.environ.get("SLACK_CATCHUP_WEBHOOK_URL")
            or os.environ.get("SLACK_WEBHOOK_URL")
        )
        notifier = SlackNotifier(webhook_url=catchup_webhook)
        ok = notifier._send(  # noqa: SLF001 - intentional reuse
            {
                "text": msg,
                "mrkdwn": True,
                "unfurl_links": False,
                "unfurl_media": False,
            }
        )
        if ok:
            dedup.mark_sent(capped)
            logger.info("catchup: posted %d items to Slack", len(capped))
        else:
            logger.error("catchup: slack post FAILED — items NOT marked as sent")
        return {
            "fetched": len(raw),
            "new": len(new),
            "sent": len(capped) if ok else 0,
            "ok": ok,
        }
    finally:
        dedup.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    dry = os.environ.get("CATCHUP_DRY_RUN") == "1"
    stats = run(dry_run=dry)
    print(f"DONE: {stats}")
