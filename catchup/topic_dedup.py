"""Topic-level duplicate collapsing for the catchup digest.

The SQLite dedup (dedup.py) only blocks the *same item* from the *same
source*, and runner.py's URL pass only blocks the *same URL*. Neither
catches the common annoyance: three different sources (HN + Reddit +
official blog) all covering the same announcement, which then shows up
three times in one digest (user feedback 2026-07-12).

This module asks gemma4 to group items that report the same story and
keeps only the best-ranked item per group (input order = tier priority,
so "first" is already "best"). Dropped duplicates are returned to the
caller so it can still mark them as sent in the SQLite dedup — otherwise
they would resurface in tomorrow's digest.

Fail-open by design: any LLM/parse problem returns the input unchanged.
A digest with duplicates beats a digest that is missing stories.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# One grouping call covers this many items. 30 numbered titles fit
# comfortably in gemma4's context; the runner never sends more anyway.
_MAX_ITEMS = 40

_PROMPT = """あなたはニュース編集者です。以下はAIニュースの見出し一覧です。

同じ出来事・同じ発表を報じている見出しのグループを見つけてください。

ルール:
- 「明らかに同一の出来事・発表・リリース」だけをグループにする
- 同じ企業の別の話題は別物として扱う（例: OpenAIの新モデル発表と、OpenAIの人事の話は別）
- 迷ったらグループにしない
- 重複が無ければ空の配列を返す

出力は JSON の配列のみ。説明文は一切書かない。
形式: [[番号, 番号], [番号, 番号, 番号]]  (番号は下の一覧の番号)

見出し一覧:
{listing}
"""


def _parse_groups(raw: str, n_items: int) -> list[list[int]]:
    """Extract [[1,4],[7,12]] from LLM output. Invalid parts are dropped."""
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    groups: list[list[int]] = []
    seen: set[int] = set()
    for g in data:
        if not isinstance(g, list):
            continue
        idxs = sorted(
            {i for i in g if isinstance(i, int) and 1 <= i <= n_items}
        )
        # A valid group has >=2 distinct items, none already grouped.
        if len(idxs) < 2 or any(i in seen for i in idxs):
            continue
        seen.update(idxs)
        groups.append(idxs)
    return groups


def collapse_duplicates(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (kept, dropped_duplicates).

    *items* must already be in priority order (tier, then recency) —
    the first item of each duplicate group is the one kept. Kept items
    gain ``also_sources``: the source names of their dropped twins.
    """
    if len(items) < 2:
        return items, []
    subset = items[:_MAX_ITEMS]

    listing = "\n".join(
        f"{i}. [{it['source']}] {it.get('title', '').strip()[:120]}"
        for i, it in enumerate(subset, 1)
    )
    try:
        from generators.llm_config import get_llm

        raw = get_llm("summarizer").generate(
            _PROMPT.format(listing=listing), temperature=0.1
        )
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("topic_dedup: LLM call failed (%s) — keeping all", exc)
        return items, []

    groups = _parse_groups(raw, len(subset))
    if not groups:
        logger.info("topic_dedup: no same-story duplicates found")
        return items, []

    drop_idx: set[int] = set()
    for g in groups:
        keeper = subset[g[0] - 1]
        twins = [subset[i - 1] for i in g[1:]]
        keeper["also_sources"] = sorted(
            {t["source"] for t in twins} - {keeper["source"]}
        )
        drop_idx.update(g[1:])
        logger.info(
            "topic_dedup: '%s' also covered by %s — collapsed %d item(s)",
            keeper.get("title", "")[:60],
            ", ".join(keeper["also_sources"]) or "same source",
            len(twins),
        )

    kept = [it for i, it in enumerate(subset, 1) if i not in drop_idx]
    dropped = [it for i, it in enumerate(subset, 1) if i in drop_idx]
    kept.extend(items[_MAX_ITEMS:])  # anything beyond the LLM window
    return kept, dropped
