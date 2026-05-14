"""Evergreen-topic collector for note.

Replaces Google Trends as the primary source of note article seeds.
The editorial direction for note is self-help / knowledge sharing
(see CLAUDE.md — the 5 pillars: k_beauty / hidden_gourmet / coffee_barista
/ self_improvement / ai_sidejob). Trending news keywords produced
hallucinated articles with placeholder text (2026-04-23 incident); an
evergreen knowledge pool lets the pipeline plan content around reader
pain-points that the LLM can actually satisfy without inventing facts.

Pool format: ``data/knowledge_topics.json`` — see that file's
``_readme`` for the schema. This collector:

* Loads every topic from the pool.
* Filters out topics whose ``id`` appears in the local cooldown log
  within their ``cooldown_days`` window (avoids re-running the same
  topic repeatedly).
* Samples up to ``max_results`` topics weighted by ``rotation_weight``.
* Emits one article dict per topic, shaped the way the generation
  pipeline already expects (``title``, ``url``, ``summary``, ``source``,
  plus a ``knowledge_topic`` block carrying the full pain/promise/outline
  so the prompt template can inject them).

The cooldown log is a plain JSONL at ``data/knowledge_cooldown.jsonl``
— each successful generation appends ``{"id": ..., "ts": ISO8601}``.
``_load_cooldown_map`` reads it once per collector instance.
"""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_POOL_PATH = _REPO / "data" / "knowledge_topics.json"
_COOLDOWN_PATH = _REPO / "data" / "knowledge_cooldown.jsonl"
_EXCLUDES_PATH = _REPO / "config" / "knowledge_topic_excludes.yaml"


def _load_excluded_ids() -> set[str]:
    """Load the committed cross-session topic exclusion list.

    The topics pool itself lives in ``data/knowledge_topics.json`` which
    is gitignored, so an operator decision like "stop generating this
    topic" needs a portable home. ``config/knowledge_topic_excludes.yaml``
    is that home. Returns an empty set if the file is missing or
    unreadable — soft-fail so missing config doesn't break collection.
    """
    if not _EXCLUDES_PATH.exists():
        return set()
    try:
        import yaml  # local import to avoid hard-dep at module import time
        with _EXCLUDES_PATH.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        ids = data.get("excluded_ids") or []
        return {str(x) for x in ids if x}
    except Exception:  # noqa: BLE001
        return set()


class KnowledgeTopicsCollector:
    """Load the evergreen topic pool and sample active topics.

    Args:
        max_results: Upper bound on the number of topic-articles emitted.
            The generation pipeline only picks a handful per run so a
            modest default keeps the candidate list readable.
            Overridable via env ``KNOWLEDGE_TOPICS_MAX_RESULTS`` for
            ad-hoc batch runs (e.g., themed mass-production).
        rng: Optional ``random.Random`` for reproducibility in tests.

    Env overrides (intentionally undocumented in CLAUDE.md — these are
    ad-hoc knobs for operator batches, not part of the steady-state
    pipeline contract):

    - ``KNOWLEDGE_TOPICS_MAX_RESULTS`` — bump the pick count for one run.
    - ``KNOWLEDGE_TOPICS_CATEGORY`` — restrict sampling to a single
      ``category`` value (e.g. ``ai_sidejob``). Comma-separated list also
      accepted. Empty string disables the filter.
    """

    def __init__(
        self,
        max_results: int = 8,
        rng: random.Random | None = None,
    ) -> None:
        env_max = os.environ.get("KNOWLEDGE_TOPICS_MAX_RESULTS", "").strip()
        if env_max:
            try:
                max_results = int(env_max)
                logger.info(
                    "knowledge topics: KNOWLEDGE_TOPICS_MAX_RESULTS=%d (env override)",
                    max_results,
                )
            except ValueError:
                logger.warning(
                    "KNOWLEDGE_TOPICS_MAX_RESULTS=%r is not int — ignored",
                    env_max,
                )
        self.max_results = max_results
        self._rng = rng or random.Random()
        env_cat = os.environ.get("KNOWLEDGE_TOPICS_CATEGORY", "").strip()
        self._category_filter: set[str] | None = None
        if env_cat:
            self._category_filter = {
                c.strip() for c in env_cat.split(",") if c.strip()
            }
            logger.info(
                "knowledge topics: KNOWLEDGE_TOPICS_CATEGORY=%s (filter active)",
                sorted(self._category_filter),
            )

    def collect(self) -> list[dict[str, Any]]:
        if not _POOL_PATH.exists():
            logger.warning(
                "knowledge topic pool missing: %s", _POOL_PATH,
            )
            return []
        try:
            pool = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("knowledge topic pool load failed: %s", exc)
            return []

        topics = pool.get("topics") or []
        if not topics:
            return []

        if self._category_filter:
            before = len(topics)
            topics = [
                t for t in topics
                if str(t.get("category", "")) in self._category_filter
            ]
            logger.info(
                "knowledge topics: category filter %s reduced pool %d -> %d",
                sorted(self._category_filter), before, len(topics),
            )
            if not topics:
                return []

        cooldown_map = self._load_cooldown_map()
        excluded_ids = _load_excluded_ids()
        now = datetime.now(timezone.utc)
        eligible: list[dict[str, Any]] = []
        for t in topics:
            tid = t.get("id")
            if not tid:
                continue
            # Cross-session permanent exclude (committed in
            # config/knowledge_topic_excludes.yaml). data/ is gitignored
            # so the pool itself isn't portable; this list is.
            if tid in excluded_ids:
                continue
            # Honour explicit disable: rotation_weight=0 or disabled_reason
            # set means "don't sample this topic at all". Pre-2026-05-14 the
            # weighted sampler floored to 0.01, so disabled topics still
            # trickled through. Filter here so disable actually disables.
            # 2026-05-14 evening (Codex Critical #4): `float(... or 1.0)`
            # was treating `0` as falsy and substituting 1.0 — so a topic
            # with `rotation_weight: 0` in YAML silently re-enabled itself.
            # Distinguish "key missing / empty string" (→ default 1.0) from
            # "explicit zero" (→ honour as disable).
            _raw_rw = t.get("rotation_weight")
            if _raw_rw is None or _raw_rw == "":
                rw = 1.0
            else:
                try:
                    rw = float(_raw_rw)
                except (TypeError, ValueError):
                    rw = 1.0
            if rw <= 0 or t.get("disabled_reason"):
                continue
            last_used = cooldown_map.get(tid)
            cooldown_days = int(t.get("cooldown_days") or 30)
            if last_used and (now - last_used) < timedelta(days=cooldown_days):
                continue
            eligible.append(t)

        if not eligible:
            logger.info(
                "knowledge topics: all %d topics on cooldown",
                len(topics),
            )
            return []

        # Weighted sampling without replacement. Defensive floor of
        # 0.01 on weight so a zero-weight topic still has a trickle of
        # chance (otherwise a typo would silently kill rotation).
        picks: list[dict[str, Any]] = []
        remaining = list(eligible)
        for _ in range(min(self.max_results, len(remaining))):
            weights = [
                max(float(r.get("rotation_weight") or 1.0), 0.01)
                for r in remaining
            ]
            chosen = self._rng.choices(remaining, weights=weights, k=1)[0]
            picks.append(chosen)
            remaining.remove(chosen)

        articles: list[dict[str, Any]] = []
        for t in picks:
            articles.append(self._to_article(t))

        logger.info(
            "knowledge topics sampled: %d / %d eligible (total pool=%d)",
            len(articles), len(eligible), len(topics),
        )
        return articles

    @staticmethod
    def _to_article(topic: dict[str, Any]) -> dict[str, Any]:
        """Shape a topic dict into the article dict the rest of the
        pipeline already handles.

        The generation prompt will receive the structured fields via
        the ``knowledge_topic`` key — the prompt template is responsible
        for deciding how to inject them.
        """
        persona = topic.get("persona", "")
        pain = topic.get("pain", "")
        promise = topic.get("promise", "")
        # Use the 'promise' as the seed title — it is the reader-facing
        # value proposition, which typically yields a much stronger
        # title than the pain point alone.
        seed_title = topic.get("seed_title") or promise[:70]
        # ``content`` is what the prompt template references as the
        # "元記事本文" block — for knowledge topics we synthesize it
        # from the pain + promise + outline so the LLM has a concrete
        # brief to anchor on instead of the raw title.
        synth_content = (
            f"【読者ペルソナ】{persona}\n"
            f"【読者の課題】{pain}\n"
            f"【この記事の約束】{promise}\n"
            f"【構成の骨子】{topic.get('outline', '')}"
        )
        return {
            "title": seed_title,
            "url": f"knowledge-topic://{topic.get('id')}",
            "summary": f"{persona} / 課題: {pain}",
            "source": "knowledge_topics",
            "content": synth_content,
            # trend_score drives ordering in ``rank_articles`` which
            # ``_generate_single_article`` consumes for note. The
            # editorial direction (CLAUDE.md) is knowledge-topics-first,
            # so pin the score above typical RSS trend_scores (~85) so
            # a spiking Anthropic/OpenAI news item cannot starve the
            # evergreen pool. Set to 95 — leaves room for a genuinely
            # high-priority RSS piece to bump one slot if it scores
            # higher.
            "trend_score": 95.0,
            "knowledge_topic": topic,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _load_cooldown_map(self) -> dict[str, datetime]:
        out: dict[str, datetime] = {}
        if not _COOLDOWN_PATH.exists():
            return out
        try:
            for line in _COOLDOWN_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                tid = rec.get("id")
                ts = rec.get("ts")
                if not (tid and ts):
                    continue
                try:
                    parsed = datetime.fromisoformat(ts)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                prev = out.get(tid)
                if prev is None or parsed > prev:
                    out[tid] = parsed
        except OSError as exc:
            logger.debug("cooldown log read failed: %s", exc)
        return out


def record_topic_used(topic_id: str) -> None:
    """Append a cooldown record after a topic was successfully
    generated. Safe to call from the main pipeline; failures are
    swallowed so the generation path is never broken by a logging issue.
    """
    if not topic_id:
        return
    rec = {
        "id": topic_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_COOLDOWN_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("cooldown log append failed: %s", exc)
