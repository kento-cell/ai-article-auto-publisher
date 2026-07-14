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

# --- 2026-07-13 incident #22: internal knowledge-topic URIs leaked into
# published bodies as reader-facing citations, e.g.
#   （出典: knowledge_topic://kc_006）
#   > 出典: 媒体名 — knowledge-topic://hg_007
# Root cause: prompts.yaml's citation template `出典: 媒体名 — {url}` is
# format-substituted with the article's source URL, which for
# knowledge_topics articles IS the internal `knowledge-topic://xxx` ID —
# and the literal "媒体名" example text gets copied verbatim. The prompt
# has been fixed to forbid this, but LLM compliance is probabilistic, so
# scrub here as well (runs BEFORE the scorer, so leaked citations can no
# longer inflate citation_count either).
# Codex review 2026-07-13: `\S*` was too greedy for Japanese text (no
# spaces) — `knowledge_topic://id）。続き` would eat the closing paren,
# the period, AND the next clause. Constrain to the actual ID alphabet.
_INTERNAL_URI_RE: Final[str] = r"knowledge[-_]topic://[A-Za-z0-9_\-]*"

# Inline parenthetical citation containing an internal URI or the bare
# 媒体名 placeholder: strip the whole parenthetical, keep the sentence.
# `[*＊\s]*` after the colon tolerates markdown bold (`**出典:** …`).
_INLINE_INTERNAL_CITE_RE: Final[re.Pattern[str]] = re.compile(
    r"[（(]\s*(?:出典|Source)\s*[:：][^）)]*?"
    r"(?:" + _INTERNAL_URI_RE + r"|媒体名)"
    r"[^）)]*[）)]",
    re.IGNORECASE,
)

# Blockquote whose attribution line carries an internal URI / 媒体名
# placeholder. The quote itself cannot be attributed to any real source,
# so the ENTIRE blockquote block is removed (an unattributed quote is a
# fabrication risk, worse than no quote). `Source:` included for parity
# with objective_scorer's citation counter (Codex review 2026-07-13).
_BLOCKQUOTE_INTERNAL_CITE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^>[^\n]*\n)*"                       # preceding quote lines
    r"^>\s*[*＊]*(?:出典|Source)\s*[:：][^\n]*?"
    r"(?:" + _INTERNAL_URI_RE + r"|媒体名)"
    r"[^\n]*$\n?",
    re.MULTILINE | re.IGNORECASE,
)

# Any remaining bare internal URI (table cells, 参考文献 lines, etc.).
_BARE_INTERNAL_URI_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?:出典|Source)\s*[:：]\s*)?(?:媒体名\s*[—ー–-]\s*)?"
    + _INTERNAL_URI_RE + r",?\s?",
    re.IGNORECASE,
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

    # 2c. Incident #22 (2026-07-13): strip citations that point at
    #     internal knowledge-topic URIs or the 媒体名 placeholder.
    #     Order matters: blockquote blocks first (they span lines),
    #     then inline parentheticals, then any bare URI leftovers.
    def _kill_internal_blockquote(m: re.Match[str]) -> str:
        removed.append(
            f"internal_uri_blockquote: {m.group(0).strip()[:80]!r}"
        )
        return ""

    cleaned = _BLOCKQUOTE_INTERNAL_CITE_RE.sub(
        _kill_internal_blockquote, cleaned,
    )

    def _kill_internal_inline(m: re.Match[str]) -> str:
        removed.append(f"internal_uri_inline: {m.group(0)[:80]!r}")
        return ""

    cleaned = _INLINE_INTERNAL_CITE_RE.sub(_kill_internal_inline, cleaned)

    def _kill_internal_bare(m: re.Match[str]) -> str:
        removed.append(f"internal_uri_bare: {m.group(0)[:80]!r}")
        return ""

    cleaned = _BARE_INTERNAL_URI_RE.sub(_kill_internal_bare, cleaned)

    # 3. Strip AI-disclosure footer lines. The matching is line-scoped
    #    via `^...$` + re.MULTILINE so we don't accidentally swallow
    #    surrounding paragraphs.
    def _kill_disclosure(m: re.Match[str]) -> str:
        snippet = m.group(0).strip()
        removed.append(f"ai_disclosure: {snippet[:80]!r}")
        return ""

    cleaned = _AI_DISCLOSURE_LINE_RE.sub(_kill_disclosure, cleaned)

    # 3b. Drop disclaimer/disclosure headings whose section became
    #     EMPTY after the line-kills above. Observed 2026-07-13
    #     (割れないグラス記事, review backlog #2): the LLM wrote
    #     「## ⚠️ 免責事項」 + an AI-disclosure line; step 3 killed the
    #     line and left a dangling empty heading, which also makes
    #     _ensure_ai_disclaimer skip (it sees the 免責 heading and
    #     assumes content exists).
    _empty_disclaimer_heading = re.compile(
        r"^#{1,4}[^\n]*(?:免責事項|免責|ご利用にあたって|ディスクレーマー"
        r"|disclaimer)[^\n]*\n+(?=#{1,4}\s|\Z)",
        re.MULTILINE | re.IGNORECASE,
    )

    def _kill_empty_disclaimer(m: re.Match[str]) -> str:
        removed.append(f"empty_disclaimer_heading: {m.group(0).strip()[:60]!r}")
        return ""

    cleaned = _empty_disclaimer_heading.sub(_kill_empty_disclaimer, cleaned)

    # 2d. LLM-fabricated anchor links (2026-07-15, backlog #16):
    #     `[オルビス公式 — トライアルセット](# オルビス トライアルセット)
    #      - 30日間返品保証付き。初回購入¥1,000` — a dead "#" href with a
    #     FABRICATED commercial offer attached. The whole line is
    #     promotional fiction; kill it entirely (an anchor-style URL
    #     `#fragment` never legitimately appears as a reference link
    #     in generated articles).
    _fake_anchor_line = re.compile(r"^[^\n]*\]\(\s*#[^)]*\)[^\n]*$\n?",
                                   re.MULTILINE)

    def _kill_fake_anchor(m: re.Match[str]) -> str:
        removed.append(f"fake_anchor_link: {m.group(0).strip()[:70]!r}")
        return ""

    cleaned = _fake_anchor_line.sub(_kill_fake_anchor, cleaned)

    # 3c. Doubled heading markers 「## ## 参考文献」 (review backlog #4,
    #     re-observed 5x in the 7-14 Cursor scrap) — keep one marker.
    def _fix_double_hash(m: re.Match[str]) -> str:
        removed.append(f"double_hash_heading: {m.group(0).strip()[:40]!r}")
        return m.group(1) + " "

    cleaned = re.sub(r"^(#{1,6})\s+#{1,6}\s+", _fix_double_hash, cleaned,
                     flags=re.MULTILINE)

    # 3d. 取得日 (retrieval date) year drift — the LLM writes its
    #     training-era year (「取得日: 2024年12月31日」 in 2026 articles,
    #     7-14 review C2). 取得日 means "when WE fetched the source" =
    #     generation day by definition, so normalise to today.
    import datetime as _dt
    _today = _dt.date.today()
    _today_str = f"{_today.year}年{_today.month}月{_today.day}日"

    def _fix_retrieval_date(m: re.Match[str]) -> str:
        if m.group(1) != _today_str:
            removed.append(
                f"retrieval_date_normalized: {m.group(1)!r} -> {_today_str!r}"
            )
        return f"取得日: {_today_str}"

    cleaned = re.sub(
        r"取得日\s*[:：]\s*(20\d{2}年\d{1,2}月\d{1,2}日)",
        _fix_retrieval_date, cleaned,
    )

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


# ----------------------------------------------------------------------
# Incident #23 (2026-07-13): completeness guard.
#
# LLM output that hits the length cap ends mid-sentence
# (「…4番出口周辺**から徒歩圏内に、」) or on a heading with no body
# (「### 💡 【図解】用途別 カメラ選定」). Nothing in the pipeline
# checked for this, so 3 articles — 2 of them PAID — shipped truncated.
#
# ``trim_incomplete_tail`` removes the broken trailing fragment so the
# article ends at its last COMPLETE block. ``is_incomplete`` is the
# read-only check used as a publish-time hard gate for already-stored
# content.
# ----------------------------------------------------------------------

# Characters that legitimately terminate a final line. Sentence-final
# punctuation, closing brackets/quotes, table pipes, code fences,
# markdown emphasis closers, and image/link closers.
_COMPLETE_TAIL_CHARS: Final[str] = "。．.!?！？…」』〉》】）)>|`*_~"

_HEADING_ONLY_RE: Final[re.Pattern[str]] = re.compile(r"^#{1,6}\s*\S")
_LIST_ITEM_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[*+-]|\d+\.)\s")
_HR_RE: Final[re.Pattern[str]] = re.compile(r"^(?:\*{3,}|-{3,}|_{3,})\s*$")


def _line_is_incomplete_prose(line: str) -> bool:
    """True when *line* looks like prose cut off mid-sentence."""
    stripped = line.rstrip()
    if not stripped:
        return False
    # Structural lines (list items, table rows, quotes, images, fences)
    # legitimately end without sentence-final punctuation, so only the
    # STRONG truncation signals apply to them: a comma-like ending
    # (`- 理由は、`) or an unbalanced bold marker. Codex review
    # 2026-07-13: the previous blanket exemption made `| 店名 | 駅から、|`
    # -style mid-cell cuts undetectable.
    is_structural = bool(
        _LIST_ITEM_RE.match(stripped)
        or _HR_RE.match(stripped)
        or stripped.startswith((">", "|", "!", "```", ":::"))
    )
    # Unbalanced bold marker = cut inside **emphasis** (e.g.
    # 「**【パターンB：継続的・網」). Table rows excepted — `|**A**|**B**|`
    # cell styling can legally produce odd counts on a complete row.
    if not stripped.startswith("|") and stripped.count("**") % 2 == 1:
        return True
    # Comma-or-connector ending = clearly mid-sentence (structural too,
    # but a trailing table pipe/fence char already passed above).
    if stripped[-1] in "、，,：:；;—－の":
        return True
    if is_structural:
        # 2026-07-15 (backlog #13a, ブロワー記事の実害): PROSE-STYLE list
        # items (「1. **安全設計…:** 単なる稼働時間だけでなく、…未然に防」)
        # can be cut mid-word too. Short noun items (「- 予備バッテリー」)
        # legitimately end without punctuation, so only flag LONG list
        # items — 40+ chars means it's a sentence, and a sentence needs
        # a terminal char. Tables/quotes/fences stay exempt.
        if (
            _LIST_ITEM_RE.match(stripped)
            and len(stripped) >= 40
            and stripped[-1] not in _COMPLETE_TAIL_CHARS
        ):
            return True
        return False
    # Prose that ends without any terminal punctuation.
    return stripped[-1] not in _COMPLETE_TAIL_CHARS


def _has_unclosed_code_fence(lines: list[str]) -> bool:
    """Odd number of ``` fence lines = a code block was cut open.

    Codex review 2026-07-13: a truncation inside a code block leaves
    the opening fence dangling; the fence line itself ends in a
    "complete" char so the prose heuristics never fire.
    """
    return sum(
        1 for ln in lines if ln.lstrip().startswith("```")
    ) % 2 == 1


def trim_incomplete_tail(content: str) -> tuple[str, list[str]]:
    """Drop trailing empty headings / mid-sentence fragments.

    Iterates from the end: removes (1) headings with no body after
    them, (2) the final paragraph when it reads as cut-off prose.
    Bounded to a handful of iterations so a pathological input cannot
    eat the whole article. Returns (cleaned, removal_log).
    """
    if not content:
        return content, []
    removed: list[str] = []
    lines = content.rstrip().split("\n")
    # Unclosed code fence: the truncation happened INSIDE a code block.
    # Drop everything from the dangling opening fence to the end, then
    # let the normal tail checks below clean up what remains.
    if _has_unclosed_code_fence(lines):
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].lstrip().startswith("```"):
                removed.append(
                    f"unclosed_code_fence: dropped {len(lines) - i} line(s) "
                    f"from {lines[i].strip()[:40]!r}"
                )
                lines = lines[:i]
                break
    for _ in range(6):  # safety bound
        # Find last non-empty line.
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            break
        last = lines[-1].strip()
        if _HEADING_ONLY_RE.match(last):
            removed.append(f"trailing_empty_heading: {last[:80]!r}")
            lines.pop()
            continue
        if _line_is_incomplete_prose(last):
            removed.append(f"mid_sentence_tail: {last[:80]!r}")
            lines.pop()
            continue
        break
    cleaned = "\n".join(lines).rstrip() + "\n"
    if removed:
        logger.warning(
            "trim_incomplete_tail: %d truncated block(s) removed: %s",
            len(removed), "; ".join(removed),
        )
    return cleaned, removed


def is_incomplete(content: str) -> str | None:
    """Publish-time read-only check. Returns a human-readable reason
    when *content* ends mid-sentence or on an empty heading, else None.

    Callers should strip any affiliate footer first — the injected
    「## 関連リンク」 section always ends cleanly and would mask a
    truncated editorial body.
    """
    if not content:
        return None
    lines = [ln for ln in content.rstrip().split("\n") if ln.strip()]
    if not lines:
        return None
    if _has_unclosed_code_fence(lines):
        return "コードフェンスが未閉 (コードブロック内で切断)"
    last = lines[-1].strip()
    if _HEADING_ONLY_RE.match(last):
        return f"末尾が本文ゼロの見出し: {last[:60]!r}"
    if _line_is_incomplete_prose(last):
        return f"本文が文の途中で切断: {last[:60]!r}"
    return None
