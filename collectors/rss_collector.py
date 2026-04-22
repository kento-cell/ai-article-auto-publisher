"""RSS feed collector for Japanese news and tech sources.

Collects articles from Japanese RSS feeds (Hatena Bookmark, Yahoo! News,
ITmedia, Publickey, Gigazine, Togetter, etc.) for note and Zenn content.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

# File that tracks already-collected article URLs to prevent duplicates.
_SEEN_URLS_PATH = Path(__file__).resolve().parent.parent / "data" / "seen_urls.json"

# File that persists per-feed failure counts so chronically broken
# sources (403 / 502 / DNS failures) stop being hammered on every run.
_FEED_FAILURE_PATH = Path(__file__).resolve().parent.parent / "data" / "rss_feed_failures.json"

# After this many consecutive failures a feed is muted until the cooldown
# expires — long enough to skip the next few scheduled runs but short
# enough that a real outage recovers on its own.
_FEED_FAILURE_THRESHOLD = 3
_FEED_COOLDOWN_SECONDS = 6 * 60 * 60  # 6 hours

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
    "korea_wowkorea": {
        "url": "https://wowkorea.jp/rss/news.xml",
        "name": "WoW!Korea (韓国総合ニュース)",
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
    "biteki": {
        "url": "https://www.biteki.com/feed",
        "name": "美的 (コスメ・美容)",
        "target": "note",
    },
    "wwdjapan": {
        "url": "https://www.wwdjapan.com/feed",
        "name": "WWD JAPAN (ファッション・ビューティ)",
        "target": "note",
    },
    # --- 女性誌オンライン・美容/ライフスタイルメディア ---
    # 狙い: 「あのインフルエンサー/モデルが愛用」型のトレンドを
    # 拾うためのソース群。Google Trends の芸能人/くじ系ノイズに
    # 比べて、掲載時点で編集者のファクトチェックが入っているので
    # Gemma3 が安全に書ける具体的ブランド/商品/人物固有名詞が
    # 常時流れてくる。
    "voce": {
        "url": "https://i-voce.jp/feed/",
        "name": "VOCE (コスメ・美容マガジン)",
        "target": "note",
    },
    "oggi": {
        "url": "https://oggi.jp/feed",
        "name": "Oggi (30代女性・ファッション)",
        "target": "note",
    },
    "hanako": {
        "url": "https://hanako.tokyo/feed/",
        "name": "Hanako (東京トレンド女性誌)",
        "target": "note",
    },
    "precious": {
        "url": "https://precious.jp/feed",
        "name": "Precious.jp (40代ハイエンド女性誌)",
        "target": "note",
    },
    "ldk_beauty": {
        "url": "https://the360.life/feed",
        "name": "the360.life (LDK忖度なしコスメ/ガジェット)",
        "target": "note",
    },
    "elle_japan": {
        "url": "https://www.elle.com/jp/rss/all.xml/",
        "name": "ELLE Japan (ハイファッション)",
        "target": "note",
    },
    "25ans": {
        "url": "https://www.25ans.jp/rss/all.xml/",
        "name": "25ans (エレガンス女性誌)",
        "target": "note",
    },
    "domani": {
        "url": "https://domani.shogakukan.co.jp/feed",
        "name": "Domani (30代後半女性・ライフスタイル)",
        "target": "note",
    },
    "mi_mollet": {
        "url": "https://mi-mollet.com/feed",
        "name": "mi-mollet (40代大人女性)",
        "target": "note",
    },
    # --- K-POP/韓国インフルエンサー網 ---
    "allkpop": {
        "url": "https://www.allkpop.com/feed",
        "name": "allkpop (K-POP速報・アイドル愛用品)",
        "target": "note",
    },
    # Kstyle は公式RSSが 2026-04 時点で 404 — 代替に Wow!Korea
    # の美容カテゴリフィード追加。
    "wowkorea_beauty": {
        "url": "https://news.wowkorea.jp/rss/idol.xml",
        "name": "WoW!Korea 美容・アイドル",
        "target": "note",
    },
    # --- note向け（コーヒー・グルメ・ライフスタイル） ---
    "coffee_barista_mag": {
        "url": "https://www.baristamagazine.com/feed/",
        "name": "Barista Magazine (コーヒーカルチャー)",
        "target": "note",
    },
    "coffee_sprudge": {
        "url": "https://sprudge.com/feed",
        "name": "Sprudge (コーヒーニュース)",
        "target": "note",
    },
    "tabelog_magazine": {
        "url": "https://magazine.tabelog.com/feed",
        "name": "食べログマガジン (グルメ)",
        "target": "note",
    },
    "retty_gourmet": {
        "url": "https://retty.news/feed/",
        "name": "Retty (グルメニュース)",
        "target": "note",
    },
    "ainow": {
        "url": "https://ainow.ai/feed/",
        "name": "AINOW (AI/テクノロジー)",
        "target": "note",
    },
    "roomie": {
        "url": "https://www.roomie.jp/feed",
        "name": "ROOMIE (ライフスタイル)",
        "target": "note",
    },
    "getnavi": {
        "url": "https://getnavi.jp/feed/",
        "name": "GetNavi (トレンドガジェット/ライフスタイル)",
        "target": "note",
    },
    # --- 有料記事向け（AI最先端・マネタイズ・株/上場） ---
    "openai_news": {
        # /blog/rss.xml は更新停止気味。/news/rss.xml が現行。
        "url": "https://openai.com/news/rss.xml",
        "name": "OpenAI News",
        "target": "zenn",
    },
    "the_decoder": {
        "url": "https://the-decoder.com/feed/",
        "name": "The Decoder (AI News)",
        "target": "zenn",
    },
    "huggingface_blog": {
        "url": "https://huggingface.co/blog/feed.xml",
        "name": "Hugging Face Blog",
        "target": "zenn",
    },
    "techcrunch_ai": {
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "name": "TechCrunch AI",
        "target": "zenn",
    },
    "venturebeat_ai": {
        "url": "https://venturebeat.com/category/ai/feed/",
        "name": "VentureBeat AI",
        "target": "zenn",
    },
    "verge_ai": {
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "name": "The Verge AI",
        "target": "zenn",
    },
    "semianalysis": {
        # AIハードウェア/データセンター/株価インパクトの分析記事。
        "url": "https://semianalysis.com/feed/",
        "name": "SemiAnalysis (AIインフラ・株式)",
        "target": "zenn",
    },
    "hn_anthropic_claude": {
        # AnthropicはRSSを公開していないためHN経由で動向を拾う。
        "url": "https://hnrss.org/newest?q=Anthropic+OR+Claude&points=10",
        "name": "Hacker News (Anthropic/Claude)",
        "target": "zenn",
    },
    "hn_ipo_stock": {
        "url": "https://hnrss.org/newest?q=IPO+OR+stock+AI&points=20",
        "name": "Hacker News (AI IPO/株)",
        "target": "zenn",
    },
    "producthunt": {
        "url": "https://www.producthunt.com/feed",
        "name": "Product Hunt (新ツール/プロダクト)",
        "target": "note",
    },
    "hn_ai": {
        "url": "https://hnrss.org/newest?q=AI+OR+LLM&points=30",
        "name": "Hacker News AI (30+ポイント)",
        "target": "zenn",
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

    # ------------------------------------------------------------------
    # Duplicate detection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_seen_urls() -> set[str]:
        """Load the set of previously collected article URLs."""
        if _SEEN_URLS_PATH.exists():
            try:
                data = json.loads(_SEEN_URLS_PATH.read_text(encoding="utf-8"))
                return set(data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("seen_urls.json is corrupted; starting fresh")
        return set()

    @staticmethod
    def _save_seen_urls(urls: set[str]) -> None:
        """Persist the set of seen URLs to disk."""
        _SEEN_URLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SEEN_URLS_PATH.write_text(
            json.dumps(sorted(urls), ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _load_feed_failures() -> dict[str, dict[str, Any]]:
        """Load the per-feed failure bookkeeping, creating on first run."""
        if _FEED_FAILURE_PATH.exists():
            try:
                data = json.loads(_FEED_FAILURE_PATH.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, TypeError):
                logger.warning("rss_feed_failures.json corrupted; starting fresh")
        return {}

    @staticmethod
    def _save_feed_failures(failures: dict[str, dict[str, Any]]) -> None:
        """Persist per-feed failure bookkeeping."""
        _FEED_FAILURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FEED_FAILURE_PATH.write_text(
            json.dumps(failures, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Main collection entry point
    # ------------------------------------------------------------------

    def collect(self) -> list[dict[str, Any]]:
        """Fetch and parse all configured RSS feeds.

        Applies URL-based duplicate detection so the same article is
        never returned twice across runs.

        Returns:
            List of article dicts sorted by published date (newest first).
        """
        seen_urls = self._load_seen_urls()
        articles: list[dict[str, Any]] = []

        failures = self._load_feed_failures()
        import time as _time
        now = _time.time()

        for feed_id, feed_config in self.feeds.items():
            state = failures.get(feed_id, {})
            streak = int(state.get("streak", 0))
            last_fail = float(state.get("last_fail", 0.0))
            if streak >= _FEED_FAILURE_THRESHOLD and (now - last_fail) < _FEED_COOLDOWN_SECONDS:
                cooldown_left = int((_FEED_COOLDOWN_SECONDS - (now - last_fail)) / 60)
                logger.info(
                    "%s 一時ミュート (%d回連続失敗, 残り%d分)",
                    feed_config["name"], streak, cooldown_left,
                )
                continue

            try:
                feed_articles = self._fetch_feed(
                    feed_config["url"],
                    feed_config["name"],
                )
                articles.extend(feed_articles)
                logger.info(
                    "%s: %d件取得", feed_config["name"], len(feed_articles)
                )
                # Success — clear the failure history so a one-off blip
                # doesn't permanently bias the cooldown logic.
                if feed_id in failures:
                    failures.pop(feed_id, None)
            except Exception as e:
                logger.error(
                    "%s 取得エラー: %s", feed_config["name"], e
                )
                failures[feed_id] = {
                    "streak": streak + 1,
                    "last_fail": now,
                    "last_error": str(e)[:200],
                }

        self._save_feed_failures(failures)

        # Deduplicate: drop articles whose URL was already collected
        new_articles = []
        for article in articles:
            url = article.get("url", "")
            if url and url not in seen_urls:
                new_articles.append(article)
                seen_urls.add(url)
            elif url:
                logger.debug("Duplicate skipped: %s", url)

        dupes_removed = len(articles) - len(new_articles)
        if dupes_removed:
            logger.info("重複記事スキップ: %d件", dupes_removed)

        # Persist updated seen-URL set (cap at 10,000 to avoid unbounded
        # growth). The previous `sorted()` cap kept the alphabetically
        # last 5000 URLs — effectively random wrt recency, so old
        # articles squatted and new ones got re-fetched. Prefer the
        # most recently seen 5000 instead, preserving iteration order
        # under Python 3.7+ dict insertion semantics.
        if len(seen_urls) > 10_000:
            seen_urls = set(list(seen_urls)[-5_000:])
        self._save_seen_urls(seen_urls)

        new_articles.sort(
            key=lambda a: a.get("published_date", datetime.min.replace(
                tzinfo=timezone.utc
            )),
            reverse=True,
        )
        return new_articles[:self.max_results]

    def _fetch_feed(
        self, url: str, source_name: str
    ) -> list[dict[str, Any]]:
        """Fetch and parse a single RSS feed."""
        # Rate-limiting already happens inside _fetch_url; the second
        # call we had here doubled every fetch interval for no benefit.
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
