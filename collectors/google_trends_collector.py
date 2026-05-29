"""Collector for Google Trends (Japan) via public RSS feed.

Fetches currently trending search topics in Japan from the Google Trends
RSS endpoint. No authentication required. Each trending topic includes
approximate traffic volume and related news articles.

Replaces the Bluesky collector for surfacing timely, buzz-worthy content
suitable for note articles.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree  # noqa: kept for .Element / .ParseError types
import defusedxml.ElementTree as _SafeET  # hardened parser (XXE / billion-laughs)

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

TRENDS_RSS_URL = "https://trends.google.co.jp/trending/rss?geo=JP"

# Google Trends RSS uses the "ht" namespace for custom fields.
_NS = {"ht": "https://trends.google.co.jp/trending/rss"}


class GoogleTrendsCollector(BaseCollector):
    """Collect trending topics in Japan from Google Trends RSS.

    Args:
        max_results: Maximum number of trending topics to return.
        request_timeout: HTTP timeout in seconds.
    """

    def __init__(
        self,
        max_results: int = 30,
        request_timeout: int = 30,
    ) -> None:
        super().__init__(rate_limit_seconds=1.0, request_timeout=request_timeout)
        self.max_results = max_results

    # Blocklist for trending topics that are structurally impossible
    # for Gemma3 to turn into a fact-grounded article:
    #   - Sports scores / match results (野球/NBA/サッカー individual
    #     games require live data we don't have)
    #   - Lottery numbers (宝くじ/ミニロト/ロト6/ナンバーズ) — pure
    #     number lookups, no editorial depth
    #   - Celebrity name-only trends (スキャンダル等) — high
    #     hallucination rate; we cannot verify their SNS claims
    #   - Obituaries (訃報) — extremely sensitive, often wrong early
    #   - TV program time slots / ep-specific spoilers
    _BLOCKED_KEYWORDS: list[str] = [
        # Sports live results
        "対 ", " 対", " vs ", " VS ",
        # Lottery
        "ロト", "ミニロト", "ナンバーズ", "ビンゴ5", "当選番号",
        # Score / rankings raw
        "速報", "ライブ速報",
        # Obituaries / sensitive
        "訃報", "死去", "告別式", "逝去",
        # Raw scandal-style
        "逮捕", "書類送検", "不倫報道",
    ]

    def _is_blocked(self, title: str) -> bool:
        """True when the trending title matches a structurally-noisy
        pattern Gemma3 cannot write factually.
        """
        for kw in self._BLOCKED_KEYWORDS:
            if kw in title:
                return True
        # Bare sports team / match names like "lakers" or "メッツ"
        # with no other context. Catch low-density alphanumeric
        # titles (≤ 10 ASCII chars + no Japanese) — they're almost
        # always sports-result trends.
        if re.fullmatch(r"[A-Za-z ]{1,18}", title) and len(title) <= 10:
            return True
        return False

    def collect(self) -> list[dict[str, Any]]:
        """Fetch and parse Google Trends RSS for Japan.

        Returns:
            List of article dicts with standard keys plus
            ``source_type``, ``traffic``, and ``related_articles``.
        """
        try:
            response = self._fetch_url(TRENDS_RSS_URL)
        except Exception:
            logger.error("Google Trends RSS fetch failed")
            return []

        try:
            root = _SafeET.fromstring(response.content)
        except ElementTree.ParseError:
            logger.error("Google Trends RSS XML parse failed")
            return []

        items = root.findall(".//item")
        logger.info("Google Trends: %d trending topics found", len(items))

        articles: list[dict[str, Any]] = []
        blocked_titles: list[str] = []
        # Over-fetch so the blocklist filter doesn't starve the
        # downstream ranking of note candidates.
        scan_limit = self.max_results * 3
        for item in items[:scan_limit]:
            try:
                article = self._parse_item(item)
                if not article:
                    continue
                if self._is_blocked(article.get("title", "")):
                    blocked_titles.append(article["title"])
                    continue
                articles.append(article)
                if len(articles) >= self.max_results:
                    break
            except Exception:
                logger.debug("Failed to parse trending item", exc_info=True)
                continue

        if blocked_titles:
            logger.info(
                "Google Trends: blocked %d structurally-noisy topics "
                "(%s…)",
                len(blocked_titles),
                ", ".join(blocked_titles[:5]),
            )
        logger.info("Google Trends: %d articles collected", len(articles))
        return articles

    def _parse_item(self, item: ElementTree.Element) -> dict[str, Any] | None:
        """Parse a single <item> element into an article dict."""
        title_el = item.find("title")
        if title_el is None or not (title_el.text or "").strip():
            return None
        title = title_el.text.strip()

        # Approximate traffic (e.g. "200,000+", "50,000+")
        traffic_el = item.find("ht:approx_traffic", _NS)
        traffic = traffic_el.text.strip() if traffic_el is not None and traffic_el.text else ""

        # Publication date
        pub_date_el = item.find("pubDate")
        if pub_date_el is not None and pub_date_el.text:
            try:
                from email.utils import parsedate_to_datetime
                published = parsedate_to_datetime(pub_date_el.text.strip())
            except Exception:
                published = datetime.now(timezone.utc)
        else:
            published = datetime.now(timezone.utc)

        # Related news articles
        related_articles: list[dict[str, str]] = []
        for news_item in item.findall("ht:news_item", _NS):
            news_title_el = news_item.find("ht:news_item_title", _NS)
            news_url_el = news_item.find("ht:news_item_url", _NS)
            news_source_el = news_item.find("ht:news_item_source", _NS)
            related_articles.append({
                "title": (news_title_el.text or "").strip() if news_title_el is not None else "",
                "url": (news_url_el.text or "").strip() if news_url_el is not None else "",
                "source": (news_source_el.text or "").strip() if news_source_el is not None else "",
            })

        # Build content from related articles for downstream processing
        content_parts = [f"Trending topic: {title} (traffic: {traffic})"]
        for ra in related_articles:
            if ra["title"]:
                content_parts.append(f"- {ra['title']} ({ra['source']})")
        content = "\n".join(content_parts)

        # Use the first related article URL if available, else Google Trends
        url = (
            related_articles[0]["url"]
            if related_articles and related_articles[0]["url"]
            else f"https://trends.google.co.jp/trending?geo=JP&q={quote_plus(title)}"
        )

        return self._make_article(
            title=title,
            url=url,
            source="google_trends",
            content=content,
            published_date=published,
            authors=[],
            source_type="google_trends",
            traffic=traffic,
            related_articles=related_articles,
        )
