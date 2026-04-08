"""Extract winning patterns from scraped articles for prompt learning."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


class PatternExtractor:
    """Analyze scraped articles to find common winning patterns."""

    def analyze_titles(self, articles: list[dict]) -> dict[str, Any]:
        """Extract title patterns and statistics."""
        titles = [a.get("title", "") for a in articles if a.get("title")]
        if not titles:
            return {}

        lengths = [len(t) for t in titles]
        emoji_re = re.compile(r"[\U0001F300-\U0001F9FF\u2600-\u27BF]")
        number_re = re.compile(r"\d+")

        # Common phrase patterns
        phrase_patterns = []
        for t in titles:
            if "方法" in t:
                phrase_patterns.append("〇〇する方法")
            if any(w in t for w in ["知らないと", "損する"]):
                phrase_patterns.append("知らないと損する〇〇")
            if any(w in t for w in ["徹底", "完全", "全て"]):
                phrase_patterns.append("徹底/完全/全て系")
            if "稼" in t:
                phrase_patterns.append("稼ぐ系")
            if "コツ" in t:
                phrase_patterns.append("コツ系")
            if any(w in t for w in ["まとめ", "選"]):
                phrase_patterns.append("まとめ・選")
            if "解説" in t:
                phrase_patterns.append("解説系")
            if "vs" in t.lower() or "比較" in t:
                phrase_patterns.append("比較系")

        return {
            "total_titles": len(titles),
            "avg_length": sum(lengths) / len(lengths),
            "min_length": min(lengths),
            "max_length": max(lengths),
            "emoji_usage_rate": sum(1 for t in titles if emoji_re.search(t)) / len(titles),
            "number_usage_rate": sum(1 for t in titles if number_re.search(t)) / len(titles),
            "common_phrases": Counter(phrase_patterns).most_common(10),
            "sample_titles": titles[:10],
        }

    def analyze_structure(self, articles: list[dict]) -> dict[str, Any]:
        """Extract structural statistics from detailed articles."""
        details = [a for a in articles if "h2_count" in a]
        if not details:
            return {}

        h2 = [a.get("h2_count", 0) for a in details]
        h3 = [a.get("h3_count", 0) for a in details]
        words = [a.get("word_count", 0) for a in details]
        imgs = [a.get("image_count", 0) for a in details]

        def avg(xs: list) -> float:
            return sum(xs) / len(xs) if xs else 0.0

        return {
            "sample_size": len(details),
            "avg_h2_count": avg(h2),
            "avg_h3_count": avg(h3),
            "avg_word_count": avg(words),
            "avg_image_count": avg(imgs),
            "optimal_word_range": (
                int(min(words) * 0.8) if words else 1500,
                int(max(words) * 1.2) if words else 4000,
            ),
        }

    def find_top_performers(
        self, articles: list[dict], top_n: int = 10
    ) -> list[dict]:
        """Sort by likes and return the top N."""
        sorted_articles = sorted(
            articles, key=lambda a: a.get("likes", 0), reverse=True
        )
        return sorted_articles[:top_n]

    def extract_winning_patterns(self, articles: list[dict]) -> dict[str, Any]:
        """Combined analysis: titles, structure, top performers, themes."""
        top = self.find_top_performers(articles, top_n=20)
        return {
            "title_analysis": self.analyze_titles(top),
            "structure_analysis": self.analyze_structure(top),
            "top_performers": [
                {
                    "title": a.get("title", ""),
                    "likes": a.get("likes", 0),
                    "url": a.get("url", ""),
                }
                for a in top[:10]
            ],
            "tags_distribution": self._tag_distribution(articles),
            "paid_ratio": (
                sum(1 for a in articles if a.get("is_paid"))
                / max(len(articles), 1)
            ),
        }

    def _tag_distribution(self, articles: list[dict]) -> list[tuple[str, int]]:
        """Most common tags across articles."""
        all_tags = []
        for a in articles:
            all_tags.extend(a.get("tags", []))
        return Counter(all_tags).most_common(20)
