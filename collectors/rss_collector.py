"""RSS feed collector for Japanese news and tech sources.

Collects articles from Japanese RSS feeds (Hatena Bookmark, Yahoo! News,
ITmedia, Publickey, Gigazine, Togetter, etc.) for note and Zenn content.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import feedparser

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

# Pre-configured Japanese RSS sources
DEFAULT_FEEDS: dict[str, dict[str, str]] = {
    # --- note向け（一般） ---
    "hatena_hotentry": {
        "url": "https://b.hatena.ne.jp/hotentry/it.rss",
        "name": "はてなブックマーク IT",
        "target": "note",
    },
    "hatena_general": {
        "url": "https://b.hatena.ne.jp/hotentry/general.rss",
        "name": "はてなブックマーク 総合",
        "target": "note",
    },
    "yahoo_it": {
        "url": "https://news.yahoo.co.jp/rss/topics/it.xml",
        "name": "Yahoo!ニュース IT",
        "target": "note",
    },
    "gigazine": {
        "url": "https://gigazine.net/news/rss_2.0/",
        "name": "GIGAZINE",
        "target": "note",
    },
    "togetter": {
        "url": "https://togetter.com/rss/hot",
        "name": "Togetter",
        "target": "note",
    },
    # --- note向け（韓国トレンド・美容・カルチャー） ---
    "korea_allkpop": {
        "url": "https://www.allkpop.com/feed",
        "name": "allkpop (K-POP/韓国カルチャー)",
        "target": "note",
    },
    "korea_soompi": {
        "url": "https://www.soompi.com/feed",
        "name": "Soompi (韓国エンタメ)",
        "target": "note",
    },
    "korea_koreaboo": {
        "url": "https://www.koreaboo.com/feed/",
        "name": "Koreaboo (韓国トレンド)",
        "target": "note",
    },
    "korea_koreaherald": {
        "url": "https://www.koreaherald.com/common/rss_xml.php?ct=102",
        "name": "Korea Herald (韓国ニュース/ライフスタイル)",
        "target": "note",
    },
    "beautynesia": {
        "url": "https://www.beautynesia.id/feed",
        "name": "Beautynesia (アジア美容)",
        "target": "note",
    },
    "cosme_ranking": {
        "url": "https://www.cosme.net/rss/pickup.xml",
        "name": "@cosme (コスメ・美容)",
        "target": "note",
    },
    # --- Zenn向け（技術） ---
    "publickey": {
        "url": "https://www.publickey1.jp/atom.xml",
        "name": "Publickey",
        "target": "zenn",
    },
    "itmedia_ai": {
        "url": "https://rss.itmedia.co.jp/rss/2.0/ait.xml",
        "name": "ITmedia AI+",
        "target": "zenn",
    },
    "zenn_trending": {
        "url": "https://zenn.dev/feed",
        "name": "Zenn トレンド",
        "target": "zenn",
    },
    "hatena_tech": {
        "url": "https://b.hatena.ne.jp/hotentry/it.rss",
        "name": "はてなブックマーク テクノロジー",
        "target": "zenn",
    },
}


class RssCollector(BaseCollector):
    """Collect articles from Japanese RSS feeds.

    Args:
        feeds: Dict of feed configs. Defaults to DEFAULT_FEEDS.
        target_platform: Filter feeds by target ("zenn", "note", or None for all).
        max_results: Maximum articles to return per feed.
        rate_limit_seconds: Delay between feed fetches.
    """

    def __init__(
        self,
        feeds: dict[str, dict[str, str]] | None = None,
        target_platform: str | None = None,
        max_results: int = 10,
        rate_limit_seconds: float = 1.0,
    ) -> None:
        super().__init__(rate_limit_seconds=rate_limit_seconds)
        all_feeds = feeds or DEFAULT_FEEDS
        if target_platform:
            self.feeds = {
                k: v for k, v in all_feeds.items()
                if v.get("target") == target_platform
            }
        else:
            self.feeds = all_feeds
        self.max_results = max_results

    def collect(self) -> list[dict[str, Any]]:
        """Fetch and parse all configured RSS feeds.

        Returns:
            List of article dicts sorted by published date (newest first).
        """
        articles: list[dict[str, Any]] = []

        for feed_id, feed_config in self.feeds.items():
            try:
                feed_articles = self._fetch_feed(
                    feed_config["url"],
                    feed_config["name"],
                )
                articles.extend(feed_articles)
                logger.info(
                    "%s: %d件取得", feed_config["name"], len(feed_articles)
                )
            except Exception as e:
                logger.error(
                    "%s 取得エラー: %s", feed_config["name"], e
                )

        articles.sort(
            key=lambda a: a.get("published_date", datetime.min.replace(
                tzinfo=timezone.utc
            )),
            reverse=True,
        )
        return articles[:self.max_results]

    def _fetch_feed(
        self, url: str, source_name: str
    ) -> list[dict[str, Any]]:
        """Fetch and parse a single RSS feed."""
        self._wait_for_rate_limit()
        response = self._fetch_url(url)
        feed = feedparser.parse(response.text)

        articles = []
        for entry in feed.entries[:self.max_results]:
            articles.append(self._parse_entry(entry, source_name))
        return articles

    def _parse_entry(
        self, entry: Any, source_name: str
    ) -> dict[str, Any]:
        """Convert a feedparser entry to a standard article dict."""
        published_str = getattr(entry, "published", "") or getattr(
            entry, "updated", ""
        )
        try:
            published_date = self._parse_date(published_str)
        except (ValueError, TypeError):
            published_date = datetime.now(timezone.utc)

        content = ""
        if hasattr(entry, "summary"):
            content = self._clean_text(entry.summary)
        elif hasattr(entry, "description"):
            content = self._clean_text(entry.description)

        return self._make_article(
            title=getattr(entry, "title", ""),
            url=getattr(entry, "link", ""),
            source=source_name,
            content=content,
            published_date=published_date,
            authors=[],
        )
