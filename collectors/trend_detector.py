"""Trend detection and scoring for collected articles.

Assigns a 0--100 trend score to each article based on recency, social
signals, and source authority.  Also clusters articles into trending
topics using simple keyword overlap.
"""

import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Weights for each scoring factor (must sum to 1.0).
_WEIGHT_RECENCY = 0.40
_WEIGHT_SOCIAL = 0.35
_WEIGHT_AUTHORITY = 0.25

# Source authority scores (0-1).  Unknown sources get a default.
SOURCE_AUTHORITY: dict[str, float] = {
    "arxiv": 0.90,
    "reddit/r/MachineLearning": 0.75,
    "reddit/r/programming": 0.70,
    "reddit/r/artificial": 0.65,
    "reddit/r/technology": 0.60,
    "bluesky": 0.70,
}
_DEFAULT_AUTHORITY = 0.50

# Recency half-life in hours -- score halves every this many hours.
_RECENCY_HALF_LIFE_HOURS = 48.0

# Social-signal normalisation caps.
_MAX_SCORE = 10_000
_MAX_COMMENTS = 2_000

# Minimum word length for topic keyword extraction.
_MIN_KEYWORD_LENGTH = 4

# Common English stop-words to exclude from topic extraction.
_STOP_WORDS: set[str] = {
    "about", "also", "been", "being", "could", "does", "from",
    "have", "into", "just", "like", "more", "most", "much", "only",
    "other", "over", "should", "some", "such", "than", "that",
    "them", "then", "there", "these", "they", "this", "very",
    "want", "what", "when", "where", "which", "while", "will",
    "with", "would", "your",
}


class TrendDetector:
    """Score and rank articles by trendiness.

    Args:
        authority_map: Optional custom source-authority mapping.
        recency_half_life_hours: Recency decay half-life.
    """

    def __init__(
        self,
        authority_map: dict[str, float] | None = None,
        recency_half_life_hours: float = _RECENCY_HALF_LIFE_HOURS,
    ) -> None:
        self.authority_map = authority_map or SOURCE_AUTHORITY
        self.half_life_hours = recency_half_life_hours

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_score(self, article: dict[str, Any]) -> float:
        """Return a trend score in [0, 100] for *article*.

        Args:
            article: Article dict (must contain at least ``published_date``
                and ``source``).

        Returns:
            Float trend score between 0 and 100.
        """
        recency = self._recency_score(article)
        social = self._social_score(article)
        authority = self._authority_score(article)

        raw = (
            _WEIGHT_RECENCY * recency
            + _WEIGHT_SOCIAL * social
            + _WEIGHT_AUTHORITY * authority
        )
        score = round(min(max(raw * 100, 0.0), 100.0), 2)
        return score

    def rank_articles(
        self, articles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Sort *articles* by trend score descending.

        Each article dict is augmented with a ``trend_score`` key —
        UNLESS the source already set one deliberately (e.g. the
        ``knowledge_topics`` collector pins 95.0 to ensure its
        evergreen seeds win over RSS spikes). Prior to 2026-04-23 this
        method unconditionally overwrote, collapsing the evergreen
        topics to ~12.5 because they have no date/social signal — so
        the whole knowledge-topics pivot silently didn't work and
        news feeds kept winning the note slot. Treat any existing
        ``trend_score`` as an editorial hint and leave it alone.

        Args:
            articles: List of article dicts.

        Returns:
            New list sorted by ``trend_score`` (highest first).
        """
        for article in articles:
            existing = article.get("trend_score")
            # Codex cross-check (2026-04-23): if a collector sets a
            # non-numeric ``trend_score`` (e.g. an LLM roundtrip left
            # it as a string), the sort below would crash. Treat
            # anything non-float/int as missing and recompute.
            if not isinstance(existing, (int, float)):
                article["trend_score"] = self.calculate_score(article)
            # else: keep editorial/pinned score verbatim.

        ranked = sorted(
            articles,
            key=lambda a: float(a.get("trend_score") or 0),
            reverse=True,
        )
        logger.info("Ranked %d articles by trend score", len(ranked))
        return ranked

    def detect_trending_topics(
        self,
        articles: list[dict[str, Any]],
        top_n: int = 10,
        min_cluster_size: int = 2,
    ) -> list[dict[str, Any]]:
        """Cluster articles into trending topics by keyword overlap.

        Args:
            articles: List of article dicts.
            top_n: Number of top topic clusters to return.
            min_cluster_size: Minimum articles to form a cluster.

        Returns:
            List of topic dicts with keys ``keyword``, ``count``,
            ``avg_trend_score``, and ``article_indices``.
        """
        keyword_to_indices: dict[str, list[int]] = defaultdict(list)

        for idx, article in enumerate(articles):
            keywords = self._extract_keywords(article)
            for kw in keywords:
                keyword_to_indices[kw].append(idx)

        topics: list[dict[str, Any]] = []
        for keyword, indices in keyword_to_indices.items():
            if len(indices) < min_cluster_size:
                continue
            scores = [
                articles[i].get("trend_score", self.calculate_score(articles[i]))
                for i in indices
            ]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            topics.append({
                "keyword": keyword,
                "count": len(indices),
                "avg_trend_score": round(avg_score, 2),
                "article_indices": indices,
            })

        topics.sort(key=lambda t: t["avg_trend_score"], reverse=True)
        result = topics[:top_n]
        logger.info("Detected %d trending topics", len(result))
        return result

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _recency_score(self, article: dict[str, Any]) -> float:
        """Exponential decay based on article age.  Returns 0-1."""
        published = article.get("published_date")
        if not isinstance(published, datetime):
            return 0.0
        now = datetime.now(timezone.utc)
        age_hours = max((now - published).total_seconds() / 3600.0, 0.0)
        decay = math.exp(
            -math.log(2) * age_hours / self.half_life_hours
        )
        return decay

    @staticmethod
    def _social_score(article: dict[str, Any]) -> float:
        """Normalised social signal score. Returns 0-1.

        Source-agnostic: looks for upvote-like and reply-like signals
        under any of the known per-source key names (Reddit, Bluesky,
        etc.) so new collectors inherit ranking for free.
        """
        upvotes = (
            article.get("score")
            or article.get("like_count")  # Bluesky
            or 0
        )
        replies = (
            article.get("num_comments")
            or article.get("reply_count")  # Bluesky
            or article.get("repost_count")  # Bluesky (amplification)
            or 0
        )
        # Log scaling so small-scale signals (Bluesky: tens of likes)
        # still register meaningfully against large-scale signals
        # (Reddit: thousands of upvotes). log1p(10_000) ≈ 9.21.
        upvotes = min(upvotes, _MAX_SCORE)
        replies = min(replies, _MAX_COMMENTS)
        up_norm = math.log1p(upvotes) / math.log1p(_MAX_SCORE)
        re_norm = math.log1p(replies) / math.log1p(_MAX_COMMENTS)
        return 0.7 * up_norm + 0.3 * re_norm

    def _authority_score(self, article: dict[str, Any]) -> float:
        """Source authority lookup.  Returns 0-1."""
        source = article.get("source", "")
        return self.authority_map.get(source, _DEFAULT_AUTHORITY)

    # ------------------------------------------------------------------
    # Keyword extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_keywords(article: dict[str, Any]) -> set[str]:
        """Extract lowercase keywords from title and content."""
        text = (
            article.get("title", "") + " " + article.get("content", "")
        )
        tokens = re.findall(r"[a-zA-Z]+", text.lower())
        return {
            t
            for t in tokens
            if len(t) >= _MIN_KEYWORD_LENGTH and t not in _STOP_WORDS
        }
