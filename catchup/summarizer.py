"""Local Gemma3 wrapper that produces a substantive JP digest per item.

Aim for 3-5 short lines (~250 char total) so a busy reader can grasp
*what happened, why it matters, and the key numbers* without opening
the original link.
"""
from __future__ import annotations

import logging
import re

from generators.llm_config import get_llm

logger = logging.getLogger(__name__)

_PROMPT = """\
以下は英語の AI 業界ニュースのタイトルと要約です。
日本語で 3〜5 行 (合計 250 文字以内) に再構成してください。

含めるべき要素:
1. 何が起きたか (1行)
2. 重要な数字・モデル名・固有名詞 (原文ママ)
3. 業界への含意 / なぜ注目すべきか (1〜2行)

ルール:
- 固有名詞 (会社名・モデル名・人名・金額・ベンチマーク名) は原文ママ
- 装飾語・煽り表現は禁止、事実ベースで簡潔に
- 出力は要約本文のみ。前置き・後置きは禁止
- 1行ごとに改行してOK (Slackのmrkdwnに直接貼られる)

タイトル: {title}
原文要約: {raw}

日本語要約 (3〜5行、250文字以内):
"""


def _clean(s: str) -> str:
    """Strip common LLM noise: leading bullets, "要約:" prefixes, code fences."""
    s = s.strip()
    s = re.sub(r"^```[\w]*\n?|```$", "", s, flags=re.MULTILINE).strip()
    s = re.sub(r"^(日本語要約[:：]?|要約[:：]?|[-*•]\s*)", "", s).strip()
    # Normalize whitespace within a line but preserve line breaks
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines()]
    s = "\n".join(ln for ln in lines if ln)
    return s[:600]  # hard cap so a runaway gen never overflows Slack


def summarize(items: list[dict]) -> list[dict]:
    """Add a `jp_summary` field to every item, in place. Returns the same list."""
    if not items:
        return items
    llm = get_llm("summarizer")
    for it in items:
        title = it.get("title", "")
        raw = (it.get("raw_summary") or "")[:2000]
        prompt = _PROMPT.format(title=title, raw=raw or title)
        try:
            out = llm.generate(prompt, temperature=0.3)
            it["jp_summary"] = _clean(out)
        except Exception as exc:  # noqa: BLE001
            logger.warning("summarize failed for %s: %s", title[:60], exc)
            it["jp_summary"] = ""
    return items
