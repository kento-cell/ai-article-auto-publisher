"""LLM-output sanitizer applied before objective scoring.

Local LLMs (Gemma3 in our case) reliably produce a small set of
template artifacts that no amount of prompt tuning fully prevents:

* The literal placeholder string ``架空のURL`` (the model copies it
  back from forbidden-phrase examples in the prompt).
* Multi-line ``- Tool name: <empty>`` bullet lists where every value
  is blank because the model didn't have a real URL to fill in.
* ``URLは記載しません`` / ``ここに入力`` / ``(※ 実際には...URLを入力)``
  placeholder phrases.

Rather than fight this in the prompt (which has been tried and the
model still slips), strip the artifacts before they reach the
scorer or the publisher. The article is presented to the reader
without these eyesores, and the scorer judges the cleaned text.

Public API: ``sanitize(content) -> (cleaned, removed_log)``.
"""
from __future__ import annotations

import logging
import re
from typing import Final

logger = logging.getLogger(__name__)

# Phrases that should never appear in a published article. Each
# becomes a "delete the entire line" rule so the surrounding paragraph
# isn't garbled.
_LINE_KILL_PHRASES: Final[tuple[str, ...]] = (
    "架空のURL",
    "架空 URL",
    "URLは記載しません",
    "ここに入力",
    "実際には",  # part of `(※ 実際には〇〇URLを...)` template
    "(※",       # prompt-leak marker
    "（※",
)

# AI 開示 footer / 自動生成バナー (2026-05-07 一人飯記事で残留した
# 「※本記事はAIで生成しました」「免責事項: 本記事の正確性は保証しません」
# 等)。技術解説記事で「Claude を使った」のような正常文脈は誤爆させたく
# ないので、line-kill ではなく regex で「いかにも footer 」な文だけ消す。
_AI_DISCLOSURE_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^.*(?:"
    r"本記事は[^\n]{0,20}(?:AI|ChatGPT|Claude|Gemini|GPT|生成AI|人工知能)"
    r"[^\n]{0,40}(?:生成|作成|執筆|書き起こ|構成|編集)"
    r"|本記事の[^\n]{0,30}(?:AI|ChatGPT|Claude|Gemini|GPT|生成AI|人工知能)"
    r"[^\n]{0,40}(?:生成|作成|執筆|書き起こ|構成|編集)"
    r"|AIによって(?:生成|作成|執筆|構成|編集|自動生成)された"
    r"|(?:AI|ChatGPT|Claude|Gemini|GPT)\s*(?:による|が)\s*(?:自動)?(?:生成|作成|執筆|構成|編集)"
    r"|本記事の[^\n]{0,20}(?:正確性|最新性|内容)を保証(?:するもの|いたしません)"
    r"|免責事項[:：]?\s*本記事[^\n]{0,30}(?:正確性|参考|個人)"
    r"|※\s*(?:AI|ChatGPT|Claude|Gemini|GPT|生成AI)[^\n]{0,15}(?:生成|作成|執筆|構成|編集)(?:記事|コンテンツ)"
    r"|(?:Generated|Written|Created|Produced)\s+by\s+(?:AI|ChatGPT|Claude|GPT|Gemini)"
    r").*$",
    re.MULTILINE | re.IGNORECASE,
)

# Pattern that detects 2+ consecutive bullet lines whose value after
# `:` is blank or whitespace. We collapse the entire run.
# Matches both `*` and `-` bullets, optional bold around the label.
# 2026-05-14: relaxed to allow `:` to appear either INSIDE the closing
# bold (`* **Valve公式:** \n`) or OUTSIDE (`* Valve公式: \n`). Prior
# regex required colon after the closing `**` and silently skipped
# the inside variant, leaving placeholders like `* **Valve公式:** ` in
# rejected articles. Also accepts numbered bullets (`1. label:`).
_EMPTY_BULLET_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?:\*|-|\d+\.)\s+\*{0,2}[^*:\n]{2,60}(?::\*{0,2}|\*{0,2}:)\s*\n){2,}",
)
# Single empty-bullet placeholder. The 2+ rule above misses standalone
# lines like `* Cisco公式サイト: ` that the LLM emits when it has only
# one reference. Strip them too — they trip the forbidden_phrases gate
# (`*   Cisco公式サイト: \n`) and waste a regen attempt.
# 2026-05-14 evening (Codex Medium): scope to *URL/reference placeholder*
# labels only, so `- メリット:` (parent of a nested list) and other
# legitimate section labels aren't deleted. The label must contain at
# least one of {公式|サイト|ニュース|URL|資料|出典|引用|ウェブ|HP|web|news}
# OR be a clearly-name + suffix shape (`〇〇公式`, `〇〇ニュース`).
_EMPTY_BULLET_SINGLE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:\*|-|\d+\.)\s+\*{0,2}"
    r"[^*:\n]{2,60}?"  # non-greedy label
    r"(?:公式|サイト|ニュース|URL|資料|出典|引用|ウェブ|HP|web|news|"
    r"ホームページ|レポート|論文|article)"
    r"[^*:\n]{0,20}"
    r"(?::\*{0,2}|\*{0,2}:)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def sanitize(content: str) -> tuple[str, list[str]]:
    """Strip prompt-leak artifacts and empty-value bullet runs.

    Returns the cleaned text plus a list of human-readable strings
    describing each removal — pipe these to the structured log so we
    can monitor how often the model regresses.

    Idempotent: repeated calls produce the same output.
    """
    if not content:
        return content, []

    removed: list[str] = []

    # 1. Drop entire lines containing prompt-leak phrases.
    cleaned_lines: list[str] = []
    for ln in content.splitlines(keepends=False):
        if any(p in ln for p in _LINE_KILL_PHRASES):
            removed.append(f"line_kill: {ln.strip()[:80]!r}")
            continue
        cleaned_lines.append(ln)
    cleaned = "\n".join(cleaned_lines)

    # 2. Collapse runs of empty-value bullets. Replace with a single
    #    blank line so adjacent paragraphs don't fuse together.
    def _replace_block(m: re.Match[str]) -> str:
        block = m.group(0)
        n_lines = block.count("\n")
        removed.append(f"empty_bullet_run: {n_lines} lines stripped")
        return "\n"

    cleaned = _EMPTY_BULLET_BLOCK_RE.sub(_replace_block, cleaned)

    # 2b. Strip single (non-consecutive) empty-value bullets. The block
    #     regex above only catches runs of 2+; standalone lines like
    #     `* Cisco公式サイト: ` slip through and trip publish-time
    #     forbidden_phrases. We can drop them safely because they carry
    #     no information.
    def _replace_single(m: re.Match[str]) -> str:
        removed.append(f"empty_bullet_single: {m.group(0).strip()[:80]!r}")
        return ""

    cleaned = _EMPTY_BULLET_SINGLE_RE.sub(_replace_single, cleaned)

    # 3. Strip AI-disclosure footer lines. The matching is line-scoped
    #    via `^...$` + re.MULTILINE so we don't accidentally swallow
    #    surrounding paragraphs.
    def _kill_disclosure(m: re.Match[str]) -> str:
        snippet = m.group(0).strip()
        removed.append(f"ai_disclosure: {snippet[:80]!r}")
        return ""

    cleaned = _AI_DISCLOSURE_LINE_RE.sub(_kill_disclosure, cleaned)

    # 4. Tidy up: collapse 3+ consecutive blank lines to 2.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    if removed:
        logger.info(
            "content_sanitizer: %d artifact(s) stripped (%d chars → %d chars)",
            len(removed),
            len(content),
            len(cleaned),
        )
        for r in removed:
            logger.debug("content_sanitizer:   %s", r)

    return cleaned, removed
