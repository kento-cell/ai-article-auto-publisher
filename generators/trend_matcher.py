"""Trend alignment scorer.

Scores an article by how well its title/summary overlaps with
currently trending vocabulary learned from note.com popular articles
(``docs/knowledge/note-trends/cumulative.json``).

Two axes are computed, the best one wins:

1. **hot**       — tokens that dominate the freshest learned samples'
   top-likes subset. "Already trending, riding the wave."
2. **emerging**  — tokens that newly appeared in the latest slice
   relative to the older baseline. "Not mainstream yet, could pop."

Either axis alone is enough to earn grade A — gatsuri-ni-notte-iru mono
mo pōten-waku no mo dochira mo hirou.

Pure stdlib; no JP tokenizer dependency. Regex-based token extraction
splits Japanese on particles/punctuation and keeps katakana/kanji/ASCII
chunks length >= 2.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DATA = Path("docs/knowledge/note-trends/cumulative.json")

# Size of each trending slice, measured in samples (not days) because
# the learn pipeline doesn't run on a fixed cadence. Newest-first.
HOT_SLICE = 500
EMERGING_SLICE = 120
BASELINE_SLICE_START = 500  # baseline = samples[500:2000]
BASELINE_SLICE_END = 2000

# Top-percentile-by-likes filter inside each slice before token extraction.
HOT_TOP_PCT = 0.25
EMERGING_TOP_PCT = 0.30  # a bit looser — small slice, fewer samples

# Grade thresholds. A requires multiple matches (gatsuri-trend) OR
# any emerging-token hit (potential novelty is rare and valuable).
HIT_A = 3

# Tokens that are too generic to carry trend signal.
STOPWORDS = {
    # Japanese common words
    "こと", "もの", "ため", "これ", "それ", "あれ", "ここ", "そこ",
    "あそこ", "今日", "明日", "昨日", "最新", "最近", "今回",
    "完全", "徹底", "簡単", "紹介", "解説", "方法", "実践", "活用",
    "使い方", "まとめ", "初心者", "入門", "記事", "無料", "有料",
    "価格", "年収", "万円", "円", "以上", "以下", "について",
    "とは", "なぜ", "どう", "いい", "いる", "する", "なる", "ある",
    # English common words
    "the", "and", "for", "with", "that", "this", "from", "you",
    "your", "are", "can", "how", "what", "why", "new", "top",
    "best", "guide", "tips", "update", "news", "ai", "vs",
    # Markup leftovers
    "https", "http", "com", "org", "jp",
}


_PARTICLE_SPLIT = re.compile(
    r"[、。！？「」『』（）【】〜・※…\s"
    r"はがをにのへでとやもからまでよりまたはおよびそしてなどです"
    r"ます\.,!?:;()\[\]{}\"'\-–—/\\|*+=#@~`^<>]+"
)
_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")
_NUMERIC = re.compile(r"^[0-9\W_]+$")


def _tokenize(text: str) -> set[str]:
    """Extract trend-candidate tokens from a Japanese/English string.

    Normalizes case for ASCII and rejects numeric-only / stopword tokens.
    Returns a *set* so repeated mentions in one title don't double-count.
    """
    if not text:
        return set()

    tokens: set[str] = set()

    # ASCII words (product names: Perplexity, ChatGPT, Claude, ...)
    for m in _ASCII_WORD.findall(text):
        w = m.lower()
        if w not in STOPWORDS and len(w) >= 3:
            tokens.add(w)

    # Japanese chunks between particles / punctuation
    for chunk in _PARTICLE_SPLIT.split(text):
        chunk = chunk.strip()
        if not chunk or len(chunk) < 2 or len(chunk) > 20:
            continue
        if _NUMERIC.match(chunk):
            continue
        if chunk.lower() in STOPWORDS:
            continue
        # Reject all-ASCII chunks (already handled above)
        if chunk.isascii():
            continue
        tokens.add(chunk)

    return tokens


class TrendMatcher:
    """Compute trend alignment grade for an article title + summary."""

    _instance: "TrendMatcher | None" = None

    def __init__(self, data_path: Path | str = _DEFAULT_DATA):
        self.data_path = Path(data_path)
        self.hot_tokens: set[str] = set()
        self.emerging_tokens: set[str] = set()
        self._loaded = False

    @classmethod
    def get(cls) -> "TrendMatcher":
        """Module-level singleton — loading 2766 samples once per run."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._ensure_loaded()
        return cls._instance

    # ------------------------------------------------------------------
    # Loading / preprocessing
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True  # always flip, even if load fails, to avoid retry loops
        if not self.data_path.exists():
            logger.warning(
                "TrendMatcher: %s not found — all articles graded C",
                self.data_path,
            )
            return
        try:
            data = json.loads(self.data_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("TrendMatcher: failed to load %s: %s", self.data_path, exc)
            return
        if not isinstance(data, list) or not data:
            logger.warning("TrendMatcher: empty or malformed data")
            return

        # Sort newest first by published_at (fallback: list order).
        def _pub_key(item: dict) -> str:
            return str(item.get("published_at") or "")

        data_sorted = sorted(data, key=_pub_key, reverse=True)

        hot_slice = data_sorted[:HOT_SLICE]
        emerge_slice = data_sorted[:EMERGING_SLICE]
        baseline_slice = data_sorted[BASELINE_SLICE_START:BASELINE_SLICE_END]

        hot_top = self._top_pct_by_likes(hot_slice, HOT_TOP_PCT)
        emerge_top = self._top_pct_by_likes(emerge_slice, EMERGING_TOP_PCT)

        # Top-likes counts drive the *trend membership* logic
        # (hot/emerging token sets). Full-slice counts drive the
        # *rate* logic for acceleration — comparing recent_rate to
        # baseline_rate only makes sense when both denominators count
        # the same kind of population (all samples, not top-likes).
        hot_counts = self._tokenize_items(hot_top)
        emerge_counts = self._tokenize_items(emerge_top)
        baseline_counts = self._tokenize_items(baseline_slice)
        emerge_full_counts = self._tokenize_items(emerge_slice)

        # Hot tokens: appear in >=3 top-recent articles, prune super-generic.
        self.hot_tokens = {
            t for t, c in hot_counts.items()
            if c >= 3 and baseline_counts.get(t, 0) < c * 5
        }

        # Emerging tokens combine two signals:
        #   (a) novelty — appeared in fresh slice but ~absent in baseline
        #   (b) acceleration — present in baseline too, but with a
        #       sharply higher per-sample frequency in the recent window
        #       (BurstSketch-inspired: comparing rates, not raw counts).
        # Either path qualifies. Exclude tokens already in hot.
        emerge_size = max(1, len(emerge_slice))
        baseline_size = max(1, len(baseline_slice))

        novelty: set[str] = {
            t for t, c in emerge_counts.items()
            if c >= 2
            and baseline_counts.get(t, 0) <= 1
            and t not in self.hot_tokens
        }

        accelerating: set[str] = set()
        for t, full_c in emerge_full_counts.items():
            if full_c < 2 or t in self.hot_tokens:
                continue
            # Rate = occurrences per sample; identical denominators on
            # both sides so the 2x check is a true rate ratio.
            recent_rate = full_c / emerge_size
            base_rate = baseline_counts.get(t, 0) / baseline_size
            if base_rate > 0 and recent_rate >= base_rate * 2.0:
                accelerating.add(t)

        self.emerging_tokens = novelty | accelerating

        logger.info(
            "TrendMatcher loaded: %d hot tokens, %d emerging tokens "
            "(novelty=%d, accel=%d) from %d samples",
            len(self.hot_tokens),
            len(self.emerging_tokens),
            len(novelty),
            len(accelerating),
            len(data_sorted),
        )

    @staticmethod
    def _top_pct_by_likes(items: list[dict], pct: float) -> list[dict]:
        if not items:
            return []
        ranked = sorted(items, key=lambda x: -(x.get("likes") or 0))
        n = max(1, int(len(ranked) * pct))
        return ranked[:n]

    @staticmethod
    def _tokenize_items(items: list[dict]) -> Counter:
        counter: Counter = Counter()
        for item in items:
            title = str(item.get("title") or "")
            counter.update(_tokenize(title))
        return counter

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(self, title: str, summary: str = "") -> dict[str, Any]:
        """Grade an article by trend alignment.

        Args:
            title: Article title (required — the main signal source).
            summary: Optional subtitle / intro paragraph for extra recall.

        Returns:
            Dict with `grade`, `hot_hits`, `emerging_hits`, matched token
            lists, and a human-readable `reason`.
        """
        self._ensure_loaded()
        haystack = f"{title} {summary}"
        haystack_lower = haystack.lower()

        # Match strategy:
        # - Japanese tokens use raw substring (compound words don't
        #   split on particles, so "副業エッセイ" must hit "エッセイ").
        # - ASCII tokens use word-boundary regex to avoid "rag" hitting
        #   "fragment" or "ai" hitting "fail". Codex review caught this.
        def _match(token_set: set[str]) -> list[str]:
            hits: list[str] = []
            for t in token_set:
                if t.isascii():
                    if re.search(rf"\b{re.escape(t)}\b", haystack_lower):
                        hits.append(t)
                elif t in haystack:
                    hits.append(t)
            return sorted(hits)

        hot_matched = _match(self.hot_tokens)
        emerge_matched = _match(self.emerging_tokens)
        hot_hits = len(hot_matched)
        emerge_hits = len(emerge_matched)
        # Emerging hits weighted higher — finding 1 emerging keyword is
        # a rarer signal than finding 1 mainstream-hot keyword.
        best = max(hot_hits, emerge_hits * 3)

        if not self.hot_tokens and not self.emerging_tokens:
            # No trend data available — don't punish the article.
            return {
                "grade": "B",
                "hot_hits": 0,
                "emerging_hits": 0,
                "hot_tokens_matched": [],
                "emerging_tokens_matched": [],
                "reason": "trend data unavailable — neutral B",
            }

        # Trend is a *bonus* dimension — A or emerging-A both lift the
        # composite score, but absence of trend signal must NOT punish
        # an otherwise-strong article (e.g. an arXiv paper irrelevant
        # to note.com vocabulary). Floor at B.
        if best >= HIT_A:
            grade = "A"
        else:
            grade = "B"

        if hot_hits > emerge_hits:
            axis = "hot"
            matched_preview = hot_matched[:5]
        elif emerge_hits > 0:
            axis = "emerging"
            matched_preview = emerge_matched[:5]
        else:
            axis = "none"
            matched_preview = []

        reason = (
            f"{axis} hits={best} "
            f"(hot={hot_hits}, emerging={emerge_hits}) "
            f"match={matched_preview}"
        )

        return {
            "grade": grade,
            "hot_hits": hot_hits,
            "emerging_hits": emerge_hits,
            "hot_tokens_matched": hot_matched,
            "emerging_tokens_matched": emerge_matched,
            "reason": reason,
        }
