"""Local Gemma wrapper that produces a substantive JP digest per item.

2026-06-16: deepened from the old 3-5 line / 250-char digest — readers
found it too thin. Now aims for a dense ~6-9 line brief (~400-550 chars)
that conveys *what happened, the concrete numbers/names, the technical
substance, why it matters, and how it differs from prior work* so the
reader gets real signal without opening the link.
"""
from __future__ import annotations

import logging
import re

from generators.llm_config import get_llm

logger = logging.getLogger(__name__)

_PROMPT = """\
以下は英語の AI 業界ニュース／論文のタイトルと要約です。
日本語で、密度の高い解説ダイジェストに再構成してください。
目安は 6〜9 行 (合計 400〜550 文字)。薄い一般論で埋めず、原文にある具体を最大限拾うこと。

必ず含める要素 (順に、各 1〜2 行):
1. 何が起きたか — 主語と動作を具体的に。誰が何を発表/公開/達成したか
2. 具体的な数字・固有名詞 — モデル名・パラメータ数・ベンチマーク名とスコア・価格・日付・社名・人名を原文ママで（拾えるだけ拾う）
3. 技術的・手法的なポイント — 何が新しいのか、どういう仕組み/アプローチか
4. 既存手法・競合との違い — 何と比べてどう優れる/異なるのか（原文にあれば）
5. 業界・実務への含意 — なぜ注目すべきか、どんな用途・影響が考えられるか

ルール:
- 固有名詞・数値は必ず原文ママ。曖昧化や丸めは禁止
- 「すごい」「画期的」等の空虚な煽りは禁止。代わりに「何がどう優れるか」を事実で書く
- 原文に無い事実を創作しない（ハルシネーション厳禁）。情報が無い要素はスキップしてよい
- 出力は要約本文のみ。前置き・後置き・見出し記号は禁止
- 1 行ごとに改行してOK (Slack mrkdwn にそのまま貼られる)
- 【最重要】原文要約が画像URLのみ・空・断片的で情報が乏しくても、必ず「タイトル」から
  読み取れる範囲（テーマ・対象技術・誰の発表か）で簡潔なダイジェストを書くこと。
  「情報が不足しています」「テキストをご提供ください」「作成できません」等の
  お断り・メタ応答・質問は絶対に出力しない（読者にそのまま配信されるため）。

タイトル: {title}
原文要約: {raw}

日本語ダイジェスト (6〜9行、400〜550文字、具体重視。情報が薄ければタイトルベースで短くてもよい):
"""


# LLM "I can't summarise this / please give me the text" refusals. When the
# source RSS carries only an image/URL, gemma4 sometimes returns a chatbot
# meta-reply instead of a digest — that must never reach Slack (2026-06-16).
_REFUSAL_RE = re.compile(
    r"(?:ご提供|提供して|お手数ですが|テキスト(?:全文)?を|"
    r"情報が(?:不足|不十分|含まれて)|読み取ることができません|"
    r"作成(?:する(?:こと)?は)?(?:でき|不可能)|恐れ入りますが)"
)


def _looks_textless(raw: str) -> bool:
    """True when raw is empty or basically just a URL/image with no prose."""
    r = (raw or "").strip()
    if len(r) < 25:
        return True
    # mostly a single URL token, no sentence punctuation / spaces
    if r.startswith("http") and (" " not in r and "。" not in r):
        return True
    return False


def _clean(s: str) -> str:
    """Strip common LLM noise: leading bullets, "要約:" prefixes, code fences.

    Returns "" when the output is a refusal/meta-reply so the digest falls
    back to showing the title alone rather than a chatbot apology.
    """
    s = s.strip()
    s = re.sub(r"^```[\w]*\n?|```$", "", s, flags=re.MULTILINE).strip()
    s = re.sub(r"^(日本語(?:ダイジェスト|要約)[:：]?|要約[:：]?|[-*•]\s*)", "", s).strip()
    # Normalize whitespace within a line but preserve line breaks
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines()]
    s = "\n".join(ln for ln in lines if ln)
    if not s:
        return ""
    # Drop a refusal that survived the prompt guard (check the first ~120
    # chars — refusals lead with the apology).
    if _REFUSAL_RE.search(s[:120]):
        return ""
    return s[:900]  # hard cap so a runaway gen never overflows Slack
    # (raised 600->900 for the 2026-06-16 denser digest)


def summarize(items: list[dict]) -> list[dict]:
    """Add a `jp_summary` field to every item, in place. Returns the same list."""
    if not items:
        return items
    llm = get_llm("summarizer")
    for it in items:
        title = it.get("title", "")
        raw = (it.get("raw_summary") or "")[:3000]  # more source context for a richer brief
        # When the feed gave us only an image/URL, summarise from the title
        # so the model writes a real (if shorter) brief instead of refusing.
        raw_for_prompt = title if _looks_textless(raw) else raw
        prompt = _PROMPT.format(title=title, raw=raw_for_prompt)
        try:
            out = llm.generate(prompt, temperature=0.3)
            it["jp_summary"] = _clean(out)
        except Exception as exc:  # noqa: BLE001
            logger.warning("summarize failed for %s: %s", title[:60], exc)
            it["jp_summary"] = ""
    return items
