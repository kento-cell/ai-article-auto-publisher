"""note.com popular article scraper for self-learning.

Fetches popular articles by category/hashtag, extracts metadata
(title, likes, structure) for pattern analysis.
Uses requests + BeautifulSoup, no Selenium overhead.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "scraped_notes"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}
_RATE_LIMIT = 2.0  # seconds between requests


class NoteScraper:
    """Scrape note.com popular articles for pattern learning."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._last_fetch = 0.0

    def _wait(self) -> None:
        elapsed = time.time() - self._last_fetch
        if elapsed < _RATE_LIMIT:
            time.sleep(_RATE_LIMIT - elapsed)
        self._last_fetch = time.time()

    def fetch_popular_articles(
        self, category: str = "business", limit: int = 30
    ) -> list[dict[str, Any]]:
        """Fetch popular articles from a note category page.

        category examples: business, tech, lifestyle, money, ai
        """
        # Check cache first
        date_key = datetime.now().strftime("%Y%m%d")
        cache_path = _CACHE_DIR / f"{date_key}_{category}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                logger.info("Loaded %d cached articles for %s", len(cached), category)
                return cached[:limit]
            except Exception:
                pass

        # Try note's API endpoint for popular articles by hashtag
        # Public endpoint: https://note.com/api/v2/hashtags/{tag}/notes
        articles = self._fetch_via_api(category, limit)
        if not articles:
            articles = self._fetch_via_html(category, limit)

        # Cache results
        if articles:
            cache_path.write_text(
                json.dumps(articles, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Cached %d articles for %s", len(articles), category)

        return articles

    def _fetch_via_api(self, category: str, limit: int) -> list[dict[str, Any]]:
        """Fetch via note v3 search API."""
        url = "https://note.com/api/v3/searches"
        params = {"context": "note", "q": category, "size": min(limit, 30)}
        try:
            self._wait()
            resp = self._session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            notes = data.get("data", {}).get("notes", {}).get("contents", [])
            results = []
            for n in notes:
                user = n.get("user", {}) or {}
                urlname = user.get("urlname", "")
                key = n.get("key", "")
                results.append({
                    "title": n.get("name", ""),
                    "url": f"https://note.com/{urlname}/n/{key}" if urlname and key else "",
                    "author": user.get("nickname", ""),
                    "likes": n.get("like_count", 0),
                    "is_paid": bool(n.get("price", 0)),
                    "price": n.get("price", 0),
                    "summary": (n.get("description") or n.get("body", "") or "")[:300],
                    "tags": [h.get("hashtag", {}).get("name", "")
                             for h in (n.get("hashtags") or [])],
                    "published_at": n.get("publish_at", ""),
                    "category": category,
                })
            return [r for r in results if r["title"]]
        except Exception as e:
            logger.warning("API fetch failed for %s: %s", category, e)
            return []

    def _fetch_via_html(self, category: str, limit: int) -> list[dict[str, Any]]:
        """Fallback: parse the HTML hashtag page."""
        url = f"https://note.com/hashtag/{category}"
        try:
            self._wait()
            resp = self._session.get(url, timeout=15)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for article in soup.select("article")[:limit]:
                title_el = article.select_one("h3, h2, [class*='title']")
                link_el = article.select_one("a[href*='/n/']")
                if not title_el or not link_el:
                    continue
                href = link_el.get("href", "")
                if href.startswith("/"):
                    href = "https://note.com" + href
                results.append({
                    "title": title_el.get_text(strip=True),
                    "url": href,
                    "likes": 0,
                    "tags": [category],
                })
            return results
        except Exception as e:
            logger.warning("HTML fetch failed for %s: %s", category, e)
            return []

    def fetch_article_detail(self, url: str) -> dict[str, Any]:
        """Fetch detailed metadata for a single article."""
        try:
            self._wait()
            resp = self._session.get(url, timeout=15)
            if resp.status_code != 200:
                return {}
            soup = BeautifulSoup(resp.text, "html.parser")
            body = soup.select_one("[class*='note-common-styles__textnote-body'], main, article")
            text = body.get_text("\n", strip=True) if body else ""

            return {
                "url": url,
                "title": (soup.select_one("h1") or soup).get_text(strip=True)[:200],
                "word_count": len(text),
                "h2_count": len(soup.select("h2")),
                "h3_count": len(soup.select("h3")),
                "image_count": len(soup.select("img")),
                "preview": text[:1000],
            }
        except Exception as e:
            logger.warning("Detail fetch failed: %s", e)
            return {}
