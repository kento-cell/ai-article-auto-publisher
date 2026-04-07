"""Collector for Reddit posts via the public JSON API.

Fetches top/hot posts from configured subreddits without requiring
OAuth credentials (uses the ``<subreddit>.json`` endpoint).
"""

import logging
from datetime import datetime, timezone
from typing import Any

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS: list[str] = [
    "programming",
    "MachineLearning",
    "artificial",
    "technology",
]

REDDIT_BASE_URL = "https://www.reddit.com"


class RedditCollector(BaseCollector):
    """Collect posts from Reddit subreddits.

    Args:
        subreddits: Subreddit names (without ``r/`` prefix).
        listing: Reddit listing type (``"hot"``, ``"top"``, ``"new"``).
        min_score: Minimum upvote score to keep a post.
        max_results: Maximum posts to return per subreddit.
        rate_limit_seconds: Minimum interval between HTTP requests.
    """

    def __init__(
        self,
        subreddits: list[str] | None = None,
        listing: str = "hot",
        min_score: int = 50,
        max_results: int = 25,
        rate_limit_seconds: float = 2.0,
    ) -> None:
        super().__init__(rate_limit_seconds=rate_limit_seconds)
        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        self.listing = listing
        self.min_score = min_score
        self.max_results = max_results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(self) -> list[dict[str, Any]]:
        """Fetch posts from all configured subreddits.

        Returns:
            List of article dicts filtered by *min_score*, sorted by
            score descending.
        """
        all_articles: list[dict[str, Any]] = []

        for subreddit in self.subreddits:
            articles = self._collect_subreddit(subreddit)
            all_articles.extend(articles)

        all_articles.sort(key=lambda a: a.get("score", 0), reverse=True)
        logger.info(
            "Collected %d Reddit posts (min_score=%d)",
            len(all_articles),
            self.min_score,
        )
        return all_articles

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_subreddit(self, subreddit: str) -> list[dict[str, Any]]:
        """Fetch and filter posts from a single subreddit."""
        url = (
            f"{REDDIT_BASE_URL}/r/{subreddit}/{self.listing}.json"
            f"?limit={self.max_results}&raw_json=1"
        )
        try:
            response = self._fetch_url(url)
            data = response.json()
        except Exception:
            logger.error("Failed to fetch r/%s", subreddit)
            return []

        posts = data.get("data", {}).get("children", [])
        articles: list[dict[str, Any]] = []

        for post in posts:
            article = self._parse_post(post.get("data", {}), subreddit)
            if article and article.get("score", 0) >= self.min_score:
                articles.append(article)

        logger.debug("r/%s: %d posts passed filter", subreddit, len(articles))
        return articles

    def _parse_post(
        self, post_data: dict[str, Any], subreddit: str
    ) -> dict[str, Any] | None:
        """Convert a Reddit post JSON object into a standard article dict."""
        if not post_data:
            return None

        created_utc = post_data.get("created_utc", 0)
        published_date = datetime.fromtimestamp(created_utc, tz=timezone.utc)

        permalink = post_data.get("permalink", "")
        post_url = f"{REDDIT_BASE_URL}{permalink}" if permalink else ""

        return self._make_article(
            title=post_data.get("title", ""),
            url=post_data.get("url", post_url),
            source=f"reddit/r/{subreddit}",
            content=post_data.get("selftext", ""),
            published_date=published_date,
            authors=[post_data.get("author", "unknown")],
            score=post_data.get("score", 0),
            num_comments=post_data.get("num_comments", 0),
            permalink=post_url,
        )
