"""Collector for Bluesky posts via the public AppView API.

Uses the unauthenticated public endpoint ``app.bsky.feed.searchPosts`` to
pull recent posts matching niche, locality-oriented queries (e.g.
"浦和 ランチ", "吉祥寺 カフェ"). Ideal for surfacing hyper-local
gourmet / lifestyle content that RSS feeds miss.

No auth, no API key. Rate-limited server-side; keep the request cadence
modest.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

BLUESKY_PUBLIC_API = "https://api.bsky.app"
SEARCH_ENDPOINT = "/xrpc/app.bsky.feed.searchPosts"

# Default locality-oriented queries. Each query is paired with a genre
# hint consumed by the downstream scorer / prompt. Keywords are mixed
# across gourmet / izakaya / coffee / lifestyle so downstream trend
# detection can rank by hit density.
_AREA_KEYWORDS: list[tuple[str, str]] = [
    ("ランチ", "gourmet"),
    ("カフェ", "coffee"),
    ("居酒屋", "izakaya"),
    ("個人店", "gourmet"),
    ("名店", "gourmet"),
    ("穴場", "lifestyle"),
]

# --- 東京 23区 + 主要な人気エリア ---
_TOKYO_AREAS: list[str] = [
    # 世田谷・目黒・渋谷ベルト（おしゃれエリア）
    "下北沢", "三軒茶屋", "用賀", "二子玉川", "自由が丘", "学芸大学",
    "中目黒", "代官山", "恵比寿", "広尾", "麻布十番", "六本木",
    "表参道", "原宿", "渋谷", "目黒", "大岡山", "奥沢", "等々力",
    "駒沢大学", "池尻大橋", "千歳烏山", "下高井戸",
    # 中央線・吉祥寺エリア
    "吉祥寺", "荻窪", "西荻窪", "中野", "高円寺", "阿佐ヶ谷", "東中野",
    "国分寺", "立川", "三鷹",
    # 神楽坂・四谷・新宿・池袋ベルト
    "神楽坂", "四谷", "新宿", "西新宿", "池袋", "要町", "江古田",
    # 下町系
    "上野", "浅草", "蔵前", "浅草橋", "両国", "門前仲町", "清澄白河",
    "月島", "人形町", "谷中", "日暮里", "根津", "千駄木",
    # 銀座・丸の内・日本橋
    "銀座", "日本橋", "神田", "秋葉原", "東京駅", "丸の内",
    # 城南・大森方面
    "戸越銀座", "大井町", "蒲田", "品川", "天王洲アイル",
    # 城北・下町北
    "赤羽", "十条", "王子", "北千住", "町屋", "錦糸町", "亀戸",
    "押上", "スカイツリー",
]

# --- 神奈川（東京近郊） ---
_KANAGAWA_AREAS: list[str] = [
    "溝の口", "武蔵小杉", "川崎", "横浜", "元町", "馬車道", "関内",
    "桜木町", "日吉", "大倉山", "菊名", "新横浜", "鎌倉", "逗子",
    "葉山", "本厚木", "海老名", "湘南", "茅ヶ崎", "藤沢",
]

# --- 埼玉 ---
_SAITAMA_AREAS: list[str] = [
    "浦和", "大宮", "川越", "所沢", "熊谷", "越谷", "川口",
]

# --- 千葉 ---
_CHIBA_AREAS: list[str] = [
    "千葉", "船橋", "柏", "松戸", "市川", "浦安", "幕張",
    "木更津", "館山", "勝浦", "銚子", "成田", "佐倉",
]

# --- 静岡 ---
_SHIZUOKA_AREAS: list[str] = [
    "静岡", "浜松", "沼津", "三島", "熱海", "伊東", "下田",
    "富士", "富士宮", "清水", "掛川", "磐田", "御殿場",
]


def _build_area_queries() -> list[dict[str, str]]:
    """Cartesian product of area × keyword with a curated keyword set.

    We don't emit every combination — that would blow out the request
    budget. Instead each area gets 2 representative queries drawn from
    the keyword list on a rotating basis so gourmet / cafe / izakaya
    coverage stays balanced.
    """
    # Interleave across prefectures so early termination (max_results)
    # still yields geographically diverse coverage.
    buckets = [
        _TOKYO_AREAS, _KANAGAWA_AREAS, _SAITAMA_AREAS,
        _CHIBA_AREAS, _SHIZUOKA_AREAS,
    ]
    all_areas: list[str] = []
    for i in range(max(len(b) for b in buckets)):
        for b in buckets:
            if i < len(b):
                all_areas.append(b[i])
    queries: list[dict[str, str]] = []
    for idx, area in enumerate(all_areas):
        # Rotate through keywords so adjacent areas pick different ones.
        kw1, g1 = _AREA_KEYWORDS[idx % len(_AREA_KEYWORDS)]
        kw2, g2 = _AREA_KEYWORDS[(idx + 2) % len(_AREA_KEYWORDS)]
        queries.append({"q": f"{area} {kw1}", "genre": g1})
        queries.append({"q": f"{area} {kw2}", "genre": g2})
    return queries


DEFAULT_QUERIES: list[dict[str, str]] = _build_area_queries() + [
    {"q": "韓国 トレンド", "genre": "korean"},
    {"q": "自家焙煎 コーヒー", "genre": "coffee"},
    {"q": "隠れ家 居酒屋", "genre": "izakaya"},
]


class BlueskyCollector(BaseCollector):
    """Collect posts from Bluesky via the public search API.

    Args:
        queries: List of ``{"q": ..., "genre": ...}`` dicts. Defaults to
            :data:`DEFAULT_QUERIES` covering Japanese locality keywords.
        lang: BCP-47 language filter (default ``"ja"``).
        min_likes: Minimum like count to keep a post (quality filter).
        limit_per_query: Number of posts fetched per query (max 100).
        max_results: Overall cap on returned articles.
        rate_limit_seconds: Minimum interval between HTTP requests.
    """

    def __init__(
        self,
        queries: list[dict[str, str]] | None = None,
        lang: str = "ja",
        min_likes: int = 2,
        limit_per_query: int = 5,
        max_results: int = 150,
        rate_limit_seconds: float = 1.2,
    ) -> None:
        super().__init__(rate_limit_seconds=rate_limit_seconds)
        self.queries = queries or DEFAULT_QUERIES
        self.lang = lang
        self.min_likes = min_likes
        self.limit_per_query = min(max(limit_per_query, 1), 100)
        self.max_results = max_results

    def collect(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen_uris: set[str] = set()

        for entry in self.queries:
            query = entry.get("q", "").strip()
            if not query:
                continue
            genre = entry.get("genre", "general")

            try:
                posts = self._search(query)
            except Exception as e:
                logger.warning("Bluesky search failed (%r): %s", query, e)
                continue

            for post in posts:
                article = self._post_to_article(post, query, genre)
                if article is None:
                    continue
                if article["url"] in seen_uris:
                    continue
                seen_uris.add(article["url"])
                results.append(article)

            if len(results) >= self.max_results:
                break

        logger.info("Bluesky: %d posts collected across %d queries",
                    len(results), len(self.queries))
        return results[: self.max_results]

    def _search(self, query: str) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "limit": self.limit_per_query,
            "lang": self.lang,
            "sort": "top",
        }
        response = self._fetch_url(
            BLUESKY_PUBLIC_API + SEARCH_ENDPOINT, params=params
        )
        data = response.json()
        return data.get("posts", []) or []

    def _post_to_article(
        self, post: dict[str, Any], query: str, genre: str
    ) -> dict[str, Any] | None:
        record = post.get("record") or {}
        text = record.get("text") or ""
        if not text.strip():
            return None

        like_count = int(post.get("likeCount") or 0)
        if like_count < self.min_likes:
            return None

        author = post.get("author") or {}
        handle = author.get("handle") or "unknown"
        display_name = author.get("displayName") or handle

        at_uri = post.get("uri") or ""
        rkey = at_uri.rsplit("/", 1)[-1] if at_uri else ""
        if not rkey:
            return None
        web_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

        created_at = record.get("createdAt") or post.get("indexedAt") or ""
        try:
            published = self._parse_bsky_date(created_at)
        except ValueError:
            published = datetime.now(timezone.utc)

        title = text.split("\n", 1)[0][:80]

        return self._make_article(
            title=title,
            url=web_url,
            source="bluesky",
            content=text,
            published_date=published,
            authors=[display_name],
            query=query,
            genre=genre,
            like_count=like_count,
            repost_count=int(post.get("repostCount") or 0),
            reply_count=int(post.get("replyCount") or 0),
        )

    @staticmethod
    def _parse_bsky_date(date_string: str) -> datetime:
        if not date_string:
            raise ValueError("empty date")
        s = date_string.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ValueError(str(e)) from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
