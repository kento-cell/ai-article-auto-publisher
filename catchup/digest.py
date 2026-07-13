"""Format catchup items into a single Slack mrkdwn message.

Tier 1 = official labs (OpenAI / Anthropic / DeepMind / Meta / NVIDIA),
Tier 2 = curated communities (HN, HF), Tier 3 = noise-prone (Reddit, arXiv).
We trim aggressively so one digest = one Slack message readable on phone.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_JST = timezone(timedelta(hours=9))

# Per-tier item caps. Raised 2026-06-16 (8/6/4 -> 10/7/5) for a meatier
# digest; the runner now chunks long output across multiple Slack messages
# so we no longer have to fit everything in one mobile-sized message.
_TIER_CAPS = {1: 10, 2: 7, 3: 5}
_TIER_HEADER = {
    1: ":fire: *Tier1 公式ラボ*",
    2: ":mag: *Tier2 コミュニティ注目*",
    3: ":speech_balloon: *Tier3 リサーチ・雑感*",
}


def _by_tier(items: list[dict], tier: int) -> list[dict]:
    out = [it for it in items if it.get("tier") == tier]
    # Newest first within tier; HN score as a tiebreaker.
    out.sort(
        key=lambda it: (
            it.get("published_at") or datetime.min,
            it.get("score") or 0,
        ),
        reverse=True,
    )
    return out[: _TIER_CAPS.get(tier, 5)]


def _fmt_time(it: dict) -> str:
    pub = it.get("published_at")
    if isinstance(pub, datetime):
        try:
            return pub.astimezone(_JST).strftime("%m/%d %H:%M")
        except (ValueError, OSError):
            return ""
    return ""


def _line(it: dict) -> str:
    title = it["title"].replace("\n", " ").strip()
    summary = (it.get("jp_summary") or "").strip()
    score = it.get("score")
    score_tag = f"  ♥{score}" if score else ""
    when = _fmt_time(it)
    when_tag = f"  ·  _{when}_" if when else ""
    body = f"*{title}*{score_tag}{when_tag}\n"
    if summary:
        # The summary is already multi-line (6-9 lines); keep the line
        # breaks so each fact reads on its own row in Slack.
        body += f"{summary}\n"
    src = it["source"]
    also = it.get("also_sources") or []
    if also:
        src += f" ほか{len(also)}ソースでも報道"
    body += f"{src} — <{it['url']}|原文を読む>"
    return body


def build(items: list[dict]) -> str:
    if not items:
        return ":sleeping: 新しい話題はありません (前回送信以降、追加なし)"
    now = datetime.now(_JST).strftime("%Y-%m-%d %H:%M JST")
    parts: list[str] = [
        f":sunrise: *AI Catchup* — {now}",
        "_(前回送信以降の新着のみ)_",
        "",
    ]
    for tier in (1, 2, 3):
        chunk = _by_tier(items, tier)
        if not chunk:
            continue
        parts.append(_TIER_HEADER[tier])
        for it in chunk:
            parts.append(_line(it))
            parts.append("")  # spacer
    return "\n".join(parts).rstrip()
