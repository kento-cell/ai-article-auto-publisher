"""Collector for arXiv CS/AI papers via the arXiv Atom API.

Uses *feedparser* to query the arXiv API and extracts metadata for
papers in the configured categories.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import feedparser  # type: ignore[import-untyped]

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES: list[str] = ["cs.AI", "cs.CL", "cs.LG", "cs.CV"]
ARXIV_API_URL = "https://export.arxiv.org/api/query"


class ArxivCollector(BaseCollector):
    """Collect papers from arXiv in selected CS/AI categories.

    Args:
        categories: arXiv category codes to query.
        max_results: Maximum number of results per query.
        sort_by: arXiv sort key (``"relevance"`` or ``"lastUpdatedDate"``).
        sort_order: ``"descending"`` or ``"ascending"``.
        rate_limit_seconds: Minimum interval between HTTP requests.
    """

    def __init__(
        self,
        categories: list[str] | None = None,
        max_results: int = 50,
        sort_by: str = "lastUpdatedDate",
        sort_order: str = "descending",
        rate_limit_seconds: float = 3.0,
    ) -> None:
        super().__init__(rate_limit_seconds=rate_limit_seconds)
        self.categories = categories or DEFAULT_CATEGORIES
        self.max_results = max_results
        self.sort_by = sort_by
        self.sort_order = sort_order

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(self) -> list[dict[str, Any]]:
        """Query arXiv and return a list of article dicts.

        Returns:
            List of article dicts sorted by published date (newest first).
        """
        query = self._build_query()
        logger.info(
            "Querying arXiv: categories=%s, max_results=%d",
            self.categories,
            self.max_results,
        )

        try:
            response = self._fetch_url(query)
        except Exception:
            logger.error("arXiv API request failed")
            return []

        feed = feedparser.parse(response.text)
        articles = [
            self._parse_entry(entry)
            for entry in feed.entries
            if self._is_relevant(entry)
        ]

        articles.sort(
            key=lambda a: a["published_date"], reverse=True
        )
        logger.info("Collected %d arXiv papers", len(articles))
        return articles

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_query(self) -> str:
        """Construct the full arXiv API query URL."""
        cat_query = " OR ".join(
            f"cat:{cat}" for cat in self.categories
        )
        params = {
            "search_query": cat_query,
            "start": 0,
            "max_results": self.max_results,
            "sortBy": self.sort_by,
            "sortOrder": self.sort_order,
        }
        return f"{ARXIV_API_URL}?{urlencode(params)}"

    def _is_relevant(self, entry: Any) -> bool:
        """Return True if *entry* belongs to at least one target category."""
        tags = [
            tag.get("term", "") for tag in getattr(entry, "tags", [])
        ]
        return any(cat in tags for cat in self.categories)

    def _parse_entry(self, entry: Any) -> dict[str, Any]:
        """Convert a feedparser entry into a standard article dict."""
        authors = [
            a.get("name", "Unknown")
            for a in getattr(entry, "authors", [])
        ]
        published_str: str = getattr(entry, "published", "")
        try:
            published_date = self._parse_date(published_str)
        except ValueError:
            logger.warning(
                "Unparseable date '%s' for entry %s; using now()",
                published_str,
                getattr(entry, "id", "?"),
            )
            published_date = datetime.now(timezone.utc)

        return self._make_article(
            title=getattr(entry, "title", ""),
            url=getattr(entry, "link", ""),
            source="arxiv",
            content=getattr(entry, "summary", ""),
            published_date=published_date,
            authors=authors,
            arxiv_id=getattr(entry, "id", ""),
            categories=[
                t.get("term", "")
                for t in getattr(entry, "tags", [])
            ],
        )
