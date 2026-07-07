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
from .sources import fetch_all_parallel
from .summarizer import summarize

logger = logging.getLogger(__name__)

# Hard ceiling on items we send to the LLM — protects against a feed
# explosion (e.g. arXiv RSS dropping 200 papers at midnight UTC).
# Raised 18->22 (2026-06-16) to match the deeper per-tier caps.
_MAX_TO_SUMMARISE = 22

# Slack renders very long messages awkwardly and may truncate; split the
# digest into chunks at item boundaries and post each as its own message.
_SLACK_CHUNK_CHARS = 3500


def _chunk(msg: str, limit: int = _SLACK_CHUNK_CHARS) -> list[str]:
    """Split a digest into <=limit-char chunks at blank-line (item)
    boundaries so no item is cut mid-way."""
    blocks = msg.split("\n\n")
    chunks: list[str] = []
    cur = ""
    for b in blocks:
        piece = (cur + "\n\n" + b) if cur else b
        if len(piece) <= limit:
            cur = piece
        else:
            if cur:
                chunks.append(cur)
            # A single block longer than the limit (rare) gets hard-split.
            while len(b) > limit:
                chunks.append(b[:limit])
                b = b[limit:]
            cur = b
    if cur:
        chunks.append(cur)
    return chunks or [msg]


def _cap(items: list[dict]) -> list[dict]:
    """Take Tier1 first, then 2, then 3, until we hit _MAX_TO_SUMMARISE."""
    by_tier = {1: [], 2: [], 3: []}
    for it in items:
        by_tier.setdefault(it.get("tier", 3), []).append(it)
    for t in by_tier:
        by_tier[t].sort(
            key=lambda it: (
                it.get("published_at").timestamp()
                if it.get("published_at") is not None
                else 0.0
            ),
            reverse=True,
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
    raw = fetch_all_parallel()
    logger.info("catchup: %d raw items fetched", len(raw))

    dedup = Dedup()
    try:
        new = dedup.filter_new(raw)
        logger.info("catchup: %d new items after dedup", len(new))

        # The same story often arrives via several sources (e.g. one URL
        # matching two HN keyword queries). Keep the first (highest-tier
        # after _cap sorting happens later) occurrence per URL.
        seen_urls: set[str] = set()
        uniq: list[dict] = []
        for it in new:
            if it["url"] in seen_urls:
                continue
            seen_urls.add(it["url"])
            uniq.append(it)
        if len(uniq) < len(new):
            logger.info("catchup: dropped %d same-URL duplicates", len(new) - len(uniq))
        new = uniq

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
        chunks = _chunk(msg)
        ok = True
        for i, chunk in enumerate(chunks, 1):
            tag = f"  ({i}/{len(chunks)})" if len(chunks) > 1 else ""
            sent_ok = notifier._send(  # noqa: SLF001 - intentional reuse
                {
                    "text": (chunk + tag) if tag else chunk,
                    "mrkdwn": True,
                    "unfurl_links": False,
                    "unfurl_media": False,
                }
            )
            ok = ok and sent_ok
            if not sent_ok:
                logger.error("catchup: slack chunk %d/%d FAILED", i, len(chunks))
                break
        if ok:
            dedup.mark_sent(capped)
            logger.info(
                "catchup: posted %d items in %d Slack message(s)",
                len(capped), len(chunks),
            )
        else:
            logger.error("catchup: slack post FAILED — items NOT marked as sent")
        return {
            "fetched": len(raw),
            "new": len(new),
            "sent": len(capped) if ok else 0,
            "messages": len(chunks),
            "ok": ok,
        }
    finally:
        dedup.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    dry = os.environ.get("CATCHUP_DRY_RUN") == "1"
    stats = run(dry_run=dry)
    print(f"DONE: {stats}")
