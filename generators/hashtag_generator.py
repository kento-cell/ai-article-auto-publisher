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
    "ai": ["AI", "人工知能", "機械学習", "テクノロジー", "AI活用"],
    "llm": ["LLM", "大規模言語モデル", "ChatGPT", "生成AI", "Claude"],
    "ai_money": ["AI副業", "AIマネタイズ", "AI収益化", "副業", "稼ぐ"],
    "ai_tools": ["AIツール", "ClaudeCode", "Cursor", "プログラミング"],
    "ai_agents": ["AIエージェント", "自動化", "AI開発", "ノーコード"],
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
    "claude code": "ai_tools", "cursor": "ai_tools", "copilot": "ai_tools",
    "v0": "ai_tools", "bolt": "ai_tools", "devin": "ai_agents",
    "マネタイズ": "ai_money", "副業": "ai_money", "収益": "ai_money",
    "saas": "ai_money", "個人開発": "ai_money",
    "エージェント": "ai_agents", "agent": "ai_agents", "自動化": "ai_agents",
    "rag": "ai", "ファインチューニング": "ai",
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

        Five layers, each contributing distinct value:
          1. Keyword-map category tags (domain: AI / gourmet / k-beauty …).
          2. Genre tags from ``_GENRE_TAG_POOLS`` mirroring the image
             mood rules so cosmetics posts land in #美容note #スキンケア
             tags that K-beauty readers actually follow.
          3. Source-based tags (allkpop → 韓流, cosme → 美容 etc).
          4. LLM-contextual tags (optional, when llm_fn present).
          5. High-reach learned tags (topic-aligned pool × recent
             popularity, see ``_learned_tags_for``).
          6. Specific-entity tags extracted from body — people /
             brands / places mentioned often enough to be
             discoverable. Lifts CTR by matching long-tail searches.

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

        # 2. Genre tag pools — mirrors ``main._IMAGE_MOOD_RULES`` so
        # image mood and hashtags stay aligned (cosmetics gets
        # pastel photos + feminine tags, AI副業 gets neon photos +
        # 副業/AI tags).
        tags.extend(self._genre_tags(title, content))

        # 3. Source-based tags
        source_tags = self._source_tags(source)
        tags.extend(source_tags)

        # 4. LLM-enhanced tags (if available)
        if llm_fn:
            llm_tags = self._llm_generate(title, content[:300], llm_fn)
            tags.extend(llm_tags)

        # 5. Blend in learned high-reach tags from the latest
        # docs/knowledge/note-trends/*_auto_learning.md. Without this
        # step hashtag output skews toward niche keyword-map tags and
        # misses the broad-discovery tags that actually drive views.
        tags.extend(self._learned_tags_for(tags))

        # 6. Entity extraction — brand names, proper nouns, people.
        # These add long-tail discovery ("BeautyofJoseon" is a narrow
        # but highly intent-matched query).
        tags.extend(self._extract_entity_tags(title, content))

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

    @staticmethod
    def _genre_tags(title: str, content: str) -> list[str]:
        """Return note-popular tags for the article's genre.

        Keyed off the same patterns as main._IMAGE_MOOD_RULES so the
        image aesthetic and the tag set describe the same audience.
        """
        import re as _re
        hay = f"{title}\n{content[:800]}"
        rules: list[tuple[str, list[str]]] = [
            (r"コスメ|美容|スキンケア|メイク|化粧|保湿|美白",
             ["美容", "コスメ", "スキンケア", "メイク好き", "韓国コスメ"]),
            (r"K-?POP|韓国アイドル|BTS|BLACKPINK|NewJeans|aespa|IVE|推し活",
             ["KPOP", "韓国アイドル", "推し活", "韓流", "エンタメ"]),
            (r"韓国|韓流|kbeauty",
             ["韓国", "韓国トレンド", "韓流", "韓国情報"]),
            (r"ダイエット|垢抜け|ボディメイク|自分磨き",
             ["ダイエット", "自分磨き", "美意識", "モテ"]),
            (r"恋愛|婚活|結婚",
             ["恋愛", "恋愛相談", "婚活", "カップル"]),
            (r"ファッション|コーデ|アパレル|ブランド",
             ["ファッション", "コーデ", "ファッション好き", "トレンド"]),
            (r"焼肉|和牛|ステーキ|肉",
             ["焼肉", "グルメ", "肉料理", "食べ歩き"]),
            (r"ラーメン|つけ麺",
             ["ラーメン", "グルメ", "麺活", "食べ歩き"]),
            (r"カフェ|コーヒー|喫茶",
             ["カフェ", "カフェ巡り", "コーヒー", "おしゃれカフェ"]),
            (r"寿司|和食|懐石",
             ["寿司", "和食", "グルメ", "食べ歩き"]),
            (r"スイーツ|パフェ|ケーキ|デザート",
             ["スイーツ", "甘いもの好き", "カフェ巡り", "グルメ"]),
            (r"AI副業|マネタイズ|収益化|稼ぐ|副業",
             ["AI副業", "副業", "マネタイズ", "稼ぐ", "フリーランス"]),
            (r"AI|ChatGPT|Claude|LLM|機械学習|人工知能",
             ["AI", "ChatGPT", "生成AI", "AI活用", "テクノロジー"]),
            (r"エンジニア|プログラミング|コーディング",
             ["エンジニア", "プログラミング", "開発", "キャリア"]),
            (r"セキュリティ|サイバー|ハッキング",
             ["セキュリティ", "情報セキュリティ", "エンジニア"]),
            (r"投資|株|資産運用|FIRE|仮想通貨|ビットコイン",
             ["投資", "資産運用", "株", "お金", "FIRE"]),
            (r"起業|スタートアップ|経営",
             ["起業", "ビジネス", "経営", "スタートアップ"]),
            (r"旅行|観光|リゾート|ホテル",
             ["旅行", "旅行記", "観光", "トラベル"]),
            (r"NBA|バスケ",
             ["NBA", "バスケ", "スポーツ"]),
            (r"野球|MLB",
             ["野球", "スポーツ", "プロ野球"]),
            (r"サッカー|フットボール|Jリーグ",
             ["サッカー", "スポーツ", "Jリーグ"]),
            (r"政治|選挙|首相|大統領|外交|国際情勢",
             ["政治", "ニュース", "国際情勢", "時事"]),
            (r"美容皮膚科|ダーマペン|エクソソーム|HIFU|美容医療",
             ["美容医療", "美容皮膚科", "美容", "自分磨き", "美意識"]),
            (r"音楽|ライブ|コンサート|アーティスト",
             ["音楽", "ライブ", "エンタメ"]),
            (r"韓ドラ|Netflix|韓国ドラマ",
             ["韓国ドラマ", "Netflix", "韓流", "エンタメ"]),
        ]
        out: list[str] = []
        for pattern, pool in rules:
            if _re.search(pattern, hay, _re.IGNORECASE):
                out.extend(pool)
                # Don't break — accumulate multiple matching genres so
                # cross-genre articles ("韓国コスメ×K-POPアイドル")
                # surface in both audiences.
        return out

    @staticmethod
    def _extract_entity_tags(title: str, content: str) -> list[str]:
        """Pull brand / product / place proper nouns for long-tail tags.

        Looks at (a) ASCII CamelCase / all-caps brand names, plus
        (b) katakana 3-15 char runs that aren't generic nouns. The
        returned list is intentionally short — the point is to add 2-3
        high-intent long-tail tags, not flood the set.
        """
        import re as _re
        from collections import Counter

        hay = f"{title}\n{content[:1200]}"

        # CamelCase / all-caps brands (Anua, BLACKPINK, LG, ChatGPT, etc).
        caps = [
            m for m in _re.findall(
                r"\b[A-Z][A-Za-z0-9]{2,18}\b", hay,
            )
            # Reject SNS boilerplate and article-shell words.
            if m.lower() not in {
                "bluesky", "twitter", "instagram", "facebook", "tiktok",
                "threads", "youtube", "linkedin", "reddit", "google",
                "note", "zenn", "qiita", "apple", "amazon", "the",
                "and", "for", "with", "this", "that", "kento",
            }
        ]
        cap_counts = Counter(caps)
        cap_tags = [t for t, c in cap_counts.most_common(3) if c >= 1]

        # Katakana 3-15 char runs (Japanese brand names). Skip
        # over-generic ones.
        kata = _re.findall(r"[゠-ヿー]{3,15}", hay)
        generic_kata = {
            "シリーズ", "ブランド", "プロジェクト", "コンセプト",
            "スタイル", "メニュー", "アイテム", "カテゴリー",
            "タイトル", "コンテンツ", "リスト",
        }
        kata_clean = [k for k in kata if k not in generic_kata]
        kata_counts = Counter(kata_clean)
        kata_tags = [t for t, c in kata_counts.most_common(2) if c >= 2]

        return cap_tags + kata_tags

    @staticmethod
    def _learned_tags_for(existing: list[str]) -> list[str]:
        """Pick a short list of learned high-reach tags aligned with the
        topic indicated by *existing* tags. Returns at most 5 tags.

        Mirrors ``scripts/publish_custom_post._blend_learned_tags`` so
        both the generate pipeline and the hand-authored custom post
        pipeline converge on the same tag strategy.
        """
        import re as _re
        from pathlib import Path as _P

        topic_pools: dict[str, list[str]] = {
            "医療|クリニック|皮膚科|エクソソーム|ダーマペン|脱毛":
                ["美容", "スキンケア", "自分磨き", "ライフスタイル",
                 "エッセイ", "心理学", "生き方", "毎日note"],
            "韓国|KPOP|アイドル|BTS|BLACKPINK|NewJeans|韓流":
                ["韓国", "美容", "スキンケア", "ライフスタイル",
                 "エッセイ", "自分磨き", "心理学"],
            "コスメ|美容|メイク|スキンケア|ダイエット|恋愛|ファッション|自分磨き":
                ["美容", "スキンケア", "ライフスタイル", "自分磨き",
                 "エッセイ", "心理学", "生き方", "毎日note"],
            "仕事|副業|ビジネス|マネタイズ|起業|フリーランス|AI|ChatGPT|Claude|人工知能":
                ["AI", "ChatGPT", "生成AI", "AI活用", "仕事", "ビジネス",
                 "副業", "フリーランス", "働き方"],
        }
        user_blob = "|".join(existing)
        preferred: list[str] = []
        for pattern, curated in topic_pools.items():
            if _re.search(pattern, user_blob, _re.IGNORECASE):
                preferred = list(curated)
                break

        learned: set[str] = set()
        try:
            root = _P(__file__).resolve().parent.parent
            knowledge = root / "docs" / "knowledge" / "note-trends"
            reports = sorted(knowledge.glob("*_auto_learning.md"), reverse=True)
            if reports:
                text = reports[0].read_text(encoding="utf-8")
                in_section = False
                for line in text.splitlines():
                    if line.startswith("## タグ分布"):
                        in_section = True
                        continue
                    if in_section:
                        if line.startswith("## "):
                            break
                        m = _re.match(
                            r"-\s*#?([^\s:：]+)\s*[:：]\s*\d+", line,
                        )
                        if m:
                            learned.add(m.group(1).lstrip("#"))
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("learned tag load failed: %s", exc)

        # Intersect preferred with learned to keep only tags that are
        # both topic-aligned AND actually popular on note. Fallback to
        # preferred directly if we couldn't load the learned list.
        if learned:
            result = [t for t in preferred if t in learned]
            if not result:
                result = preferred[:5]
        else:
            result = preferred[:5]
        return result[:5]

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
