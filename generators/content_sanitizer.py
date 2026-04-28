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

# Pattern that detects 2+ consecutive bullet lines whose value after
# `:` is blank or whitespace. We collapse the entire run.
# Matches both `*` and `-` bullets, optional bold around the label.
_EMPTY_BULLET_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?:\*|-)\s+\*{0,2}[^*:\n]{2,60}\*{0,2}:\s*\n){2,}",
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

    # 3. Tidy up: collapse 3+ consecutive blank lines to 2.
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
