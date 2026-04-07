"""Abstract base class for all article collectors.

Provides common functionality for fetching URLs, parsing dates,
cleaning text, and rate limiting across all collector implementations.
"""

import logging
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Standard keys every collected article dict must contain.
ARTICLE_KEYS = ("title", "url", "source", "content", "published_date", "authors")


class BaseCollector(ABC):
    """Abstract base for all source collectors.

    Subclasses must implement :meth:`collect` and return a list of dicts
    whose keys match :data:`ARTICLE_KEYS`.

    Args:
        rate_limit_seconds: Minimum interval between HTTP requests.
        request_timeout: Timeout in seconds for each HTTP request.
    """

    def __init__(
        self,
        rate_limit_seconds: float = 1.0,
        request_timeout: int = 30,
    ) -> None:
        self.rate_limit_seconds = rate_limit_seconds
        self.request_timeout = request_timeout
        self._last_request_time: float = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": "ai-article-auto-publisher/1.0"}
        )

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def collect(self) -> list[dict[str, Any]]:
        """Collect articles from the source.

        Returns:
            List of article dicts with keys defined in :data:`ARTICLE_KEYS`.
        """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the rate-limit interval has elapsed."""
        elapsed = time.monotonic() - self._last_request_time
        remaining = self.rate_limit_seconds - elapsed
        if remaining > 0:
            logger.debug("Rate-limit: sleeping %.2f s", remaining)
            time.sleep(remaining)

    def _fetch_url(self, url: str, **kwargs: Any) -> requests.Response:
        """Fetch *url* with rate limiting and unified error handling.

        Args:
            url: Target URL.
            **kwargs: Extra keyword args forwarded to ``requests.get``.

        Returns:
            :class:`requests.Response` on success.

        Raises:
            requests.RequestException: On network / HTTP errors.
        """
        self._wait_for_rate_limit()
        try:
            logger.debug("Fetching %s", url)
            response = self._session.get(
                url, timeout=self.request_timeout, **kwargs
            )
            response.raise_for_status()
            return response
        except requests.RequestException:
            logger.exception("Failed to fetch %s", url)
            raise
        finally:
            self._last_request_time = time.monotonic()

    @staticmethod
    def _parse_date(date_string: str) -> datetime:
        """Parse an ISO-8601-ish date string into a UTC datetime.

        Handles common variants returned by arXiv, Reddit, and RSS feeds.

        Args:
            date_string: Date string to parse.

        Returns:
            Timezone-aware :class:`datetime` in UTC.

        Raises:
            ValueError: If the string cannot be parsed.
        """
        formats = (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        )
        for fmt in formats:
            try:
                dt = datetime.strptime(date_string, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        raise ValueError(f"Unable to parse date string: {date_string!r}")

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normalise whitespace and strip HTML-ish residue.

        Args:
            text: Raw text that may contain HTML tags or excess whitespace.

        Returns:
            Cleaned plain-text string.
        """
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _make_article(
        self,
        title: str,
        url: str,
        source: str,
        content: str,
        published_date: datetime | str,
        authors: list[str],
        **extra: Any,
    ) -> dict[str, Any]:
        """Build a validated article dict.

        Args:
            title: Article title.
            url: Canonical URL.
            source: Source identifier (e.g. ``"arxiv"``).
            content: Body or abstract text.
            published_date: Publication timestamp.
            authors: List of author names.
            **extra: Additional metadata merged into the dict.

        Returns:
            Article dict with all standard keys plus *extra*.
        """
        if isinstance(published_date, str):
            published_date = self._parse_date(published_date)
        article: dict[str, Any] = {
            "title": self._clean_text(title),
            "url": url,
            "source": source,
            "content": self._clean_text(content),
            "published_date": published_date,
            "authors": authors,
        }
        article.update(extra)
        return article
