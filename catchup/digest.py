"""Format catchup items into a single Slack mrkdwn message.

Tier 1 = official labs (OpenAI / Anthropic / DeepMind / Meta / NVIDIA),
Tier 2 = curated communities (HN, HF), Tier 3 = noise-prone (Reddit, arXiv).
We trim aggressively so one digest = one Slack message readable on phone.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_JST = timezone(timedelta(hours=9))

# Cap per-tier so the message stays scrollable on mobile.
_TIER_CAPS = {1: 8, 2: 6, 3: 4}
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


def _line(it: dict) -> str:
    title = it["title"].replace("\n", " ").strip()
    summary = (it.get("jp_summary") or "").strip()
    score = it.get("score")
    score_tag = f"  ♥{score}" if score else ""
    body = (
        f"*{title}*{score_tag}\n"
        f"{summary}\n" if summary else f"*{title}*{score_tag}\n"
    )
    body += f"_{it['source']}_ — <{it['url']}|link>"
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
