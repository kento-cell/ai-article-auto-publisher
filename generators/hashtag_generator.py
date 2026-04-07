"""Automatic hashtag generation for note/Zenn articles.

Generates relevant hashtags based on article content, title, and source.
Uses keyword extraction + category mapping + LLM for contextual tags.
"""

import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Category → hashtag mappings (Japanese)
CATEGORY_TAGS: dict[str, list[str]] = {
    # テクノロジー
    "ai": ["AI", "人工知能", "機械学習", "テクノロジー"],
    "llm": ["LLM", "大規模言語モデル", "ChatGPT", "生成AI"],
    "web": ["Web開発", "フロントエンド", "バックエンド", "プログラミング"],
    "cloud": ["クラウド", "AWS", "GCP", "Azure", "インフラ"],
    "security": ["セキュリティ", "サイバーセキュリティ", "情報セキュリティ"],
    # 韓国・美容・カルチャー
    "kbeauty": ["韓国コスメ", "韓国美容", "Kビューティー", "スキンケア"],
    "kpop": ["KPOP", "韓国", "韓流", "エンタメ"],
    "ktrend": ["韓国トレンド", "韓国最新情報", "韓国カルチャー"],
    "beauty": ["美容", "コスメ", "スキンケア", "メイク"],
    "fashion": ["ファッション", "韓国ファッション", "トレンド"],
    # コーヒー・バリスタ
    "coffee": ["コーヒー", "バリスタ", "カフェ", "コーヒー好き"],
    "cafe": ["カフェ巡り", "おしゃれカフェ", "カフェ好き"],
    # グルメ・デート
    "gourmet": ["グルメ", "おすすめグルメ", "食べ歩き"],
    "izakaya": ["居酒屋", "デート", "おすすめ居酒屋", "モテ"],
    "date": ["デートスポット", "モテ", "大人デート", "おしゃれ"],
    "restaurant": ["レストラン", "ディナー", "おすすめ"],
    # ライフスタイル・自分磨き
    "lifestyle": ["ライフスタイル", "暮らし", "ライフハック", "QOL"],
    "selfcare": ["自分磨き", "美意識", "メンズ美容", "モテる"],
    "mensfashion": ["メンズファッション", "メンズコーデ", "大人の男"],
    # 一般
    "business": ["ビジネス", "仕事術", "キャリア"],
    "trend": ["トレンド", "話題", "注目"],
}

# Keyword → category mapping
KEYWORD_CATEGORIES: dict[str, str] = {
    # AI/Tech
    "machine learning": "ai", "deep learning": "ai", "neural": "ai",
    "gpt": "llm", "claude": "llm", "llm": "llm", "transformer": "llm",
    "chatgpt": "llm", "openai": "llm", "anthropic": "llm",
    "react": "web", "typescript": "web", "javascript": "web",
    "python": "web", "rust": "web", "golang": "web",
    "aws": "cloud", "kubernetes": "cloud", "docker": "cloud",
    # Coffee / Barista
    "coffee": "coffee", "コーヒー": "coffee", "バリスタ": "coffee",
    "エスプレッソ": "coffee", "ラテ": "coffee", "カフェ": "cafe",
    "ドリップ": "coffee", "焙煎": "coffee", "珈琲": "coffee",
    # Gourmet / Date
    "居酒屋": "izakaya", "デート": "date", "モテ": "date",
    "グルメ": "gourmet", "レストラン": "restaurant",
    "ディナー": "restaurant", "新宿": "gourmet", "渋谷": "gourmet",
    "恵比寿": "gourmet", "六本木": "gourmet", "銀座": "gourmet",
    # Lifestyle / Self-improvement
    "自分磨き": "selfcare", "美意識": "selfcare", "メンズ": "mensfashion",
    "ファッション": "fashion", "fashion": "fashion",
    # Korean / Beauty
    "korea": "ktrend", "korean": "ktrend", "韓国": "ktrend",
    "kpop": "kpop", "k-pop": "kpop", "bts": "kpop", "アイドル": "kpop",
    "beauty": "kbeauty", "skincare": "kbeauty", "cosmetic": "kbeauty",
    "美容": "beauty", "コスメ": "beauty", "スキンケア": "beauty",
    "メイク": "beauty", "化粧": "beauty",
    "ファッション": "fashion", "fashion": "fashion",
}


class HashtagGenerator:
    """Generate relevant hashtags for articles."""

    def __init__(self, max_tags: int = 10) -> None:
        """Initialize with max hashtag count.

        Args:
            max_tags: Maximum number of hashtags to generate.
        """
        self.max_tags = max_tags

    def generate(
        self,
        title: str,
        content: str,
        source: str = "",
        llm_fn: Optional[Callable[[str], str]] = None,
    ) -> list[str]:
        """Generate hashtags for an article.

        Combines keyword-based extraction with optional LLM enhancement.

        Args:
            title: Article title.
            content: Article body text.
            source: Source name (e.g., "allkpop", "@cosme").
            llm_fn: Optional LLM callable for contextual tag generation.

        Returns:
            List of hashtag strings (without # prefix).
        """
        tags: list[str] = []

        # 1. Keyword-based category detection
        text = f"{title} {content[:500]}".lower()
        detected_categories = self._detect_categories(text)
        for cat in detected_categories:
            tags.extend(CATEGORY_TAGS.get(cat, []))

        # 2. Source-based tags
        source_tags = self._source_tags(source)
        tags.extend(source_tags)

        # 3. LLM-enhanced tags (if available)
        if llm_fn:
            llm_tags = self._llm_generate(title, content[:300], llm_fn)
            tags.extend(llm_tags)

        # Deduplicate, preserve order, limit
        seen: set[str] = set()
        unique: list[str] = []
        for tag in tags:
            tag_clean = tag.strip().replace(" ", "")
            if tag_clean and tag_clean not in seen:
                seen.add(tag_clean)
                unique.append(tag_clean)

        result = unique[:self.max_tags]
        logger.info("Generated %d hashtags: %s", len(result), result)
        return result

    def generate_with_prefix(
        self, title: str, content: str, **kwargs
    ) -> list[str]:
        """Generate hashtags with # prefix."""
        tags = self.generate(title, content, **kwargs)
        return [f"#{tag}" for tag in tags]

    def _detect_categories(self, text: str) -> list[str]:
        """Detect content categories from text keywords."""
        categories: list[str] = []
        for keyword, category in KEYWORD_CATEGORIES.items():
            if keyword in text and category not in categories:
                categories.append(category)
        return categories[:5]

    @staticmethod
    def _source_tags(source: str) -> list[str]:
        """Return tags based on the content source."""
        source_lower = source.lower()
        if any(k in source_lower for k in ["allkpop", "soompi", "koreaboo"]):
            return ["韓国", "韓流", "最新情報"]
        if any(k in source_lower for k in ["korea herald"]):
            return ["韓国ニュース", "韓国最新情報"]
        if any(k in source_lower for k in ["cosme", "beauty"]):
            return ["美容", "コスメ", "おすすめ"]
        if any(k in source_lower for k in ["arxiv", "publickey"]):
            return ["テクノロジー", "エンジニア"]
        if any(k in source_lower for k in ["coffee", "standart", "goodcoffee"]):
            return ["コーヒー", "カフェ", "バリスタ"]
        if any(k in source_lower for k in ["tabelog", "retty"]):
            return ["グルメ", "おすすめ", "食べ歩き"]
        if any(k in source_lower for k in ["fashionsnap", "roomie"]):
            return ["ライフスタイル", "トレンド", "おしゃれ"]
        if "hatena" in source_lower:
            return ["話題", "注目"]
        return []

    @staticmethod
    def _llm_generate(
        title: str,
        content_preview: str,
        llm_fn: Callable[[str], str],
    ) -> list[str]:
        """Use LLM to generate contextual hashtags."""
        prompt = (
            "以下の記事に最適な日本語ハッシュタグを5個生成してください。\n"
            "カンマ区切りで、#なしで出力してください。\n"
            "トレンド性が高く、検索されやすいタグにしてください。\n\n"
            f"タイトル: {title}\n"
            f"内容: {content_preview}\n\n"
            "ハッシュタグ:"
        )
        try:
            response = llm_fn(prompt)
            tags = [
                t.strip().replace("#", "")
                for t in response.split(",")
                if t.strip()
            ]
            return tags[:5]
        except Exception as e:
            logger.warning("LLMハッシュタグ生成失敗: %s", e)
            return []
