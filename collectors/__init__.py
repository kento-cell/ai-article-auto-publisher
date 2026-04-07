"""Collectors package for gathering article data from various sources."""

from collectors.base_collector import BaseCollector
from collectors.arxiv_collector import ArxivCollector
from collectors.reddit_collector import RedditCollector
from collectors.trend_detector import TrendDetector

__all__ = [
    "BaseCollector",
    "ArxivCollector",
    "RedditCollector",
    "TrendDetector",
]
