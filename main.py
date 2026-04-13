"""
AI記事自動生成・投稿システム メインスクリプト

パイプライン:
  収集 → ランク付け → 生成 → 客観スコア → 主観スコア → 集約判定
  → Sheets登録（承認待ち）→ Gmail通知 → ユーザー承認 → 投稿 → 通知

承認フロー:
  1. generate: 記事を生成し、スコアリングしてSheetsに「⏳承認待ち」で登録
  2. publish:  Sheetsで「✅承認」になった記事だけを投稿
"""

import argparse
import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Fix Windows cp932 encoding for Unicode output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import yaml
from dotenv import load_dotenv

from collectors.arxiv_collector import ArxivCollector
from collectors.bluesky_collector import BlueskyCollector
from collectors.reddit_collector import RedditCollector
from collectors.rss_collector import RssCollector
from collectors.trend_detector import TrendDetector
from generators.claude_automator import ClaudeAutomator
from generators.local_llm import LocalLLM
from generators.regenerator import Regenerator
from generators.diagram_generator import DiagramGenerator
from generators.evidence_manager import EvidenceManager
from generators.hashtag_generator import HashtagGenerator
from generators.cover_generator import CoverGenerator
from generators.objective_scorer import ObjectiveScorer
from generators.subjective_evaluator import SubjectiveEvaluator
from generators.score_aggregator import ScoreAggregator
from publishers.zenn_publisher import ZennPublisher
from publishers.note_publisher import NotePublisher
from publishers.slack_notifier import SlackNotifier
from publishers.gmail_notifier import GmailNotifier
from utils.article_store import ArticleStore
from utils.sheets_manager import SheetsManager
from utils.token_manager import TokenManager, estimate_tokens
from utils.feedback_recorder import FeedbackRecorder
from utils.logger import setup_logger

load_dotenv()
logger = setup_logger(__name__)


# =====================================================================
# Structure rotation
# =====================================================================

def _select_structure(
    title: str, source: str, platform: str, prompts: dict
) -> dict | None:
    """Select an article structure pattern based on content and platform.

    Returns:
        Structure dict with name, description, outline. Or None for default.
    """
    structures = prompts.get("article_structures", [])
    selection_rules = prompts.get("structure_selection", {})
    platform_rules = selection_rules.get(platform, {}).get("rules", [])

    if not structures or not platform_rules:
        return None

    text = f"{title} {source}".lower()

    # Check rules in order
    for rule in platform_rules:
        if "keyword" in rule:
            if any(kw.lower() in text for kw in rule["keyword"]):
                return _find_structure(structures, rule["structure"])
        if "source_category" in rule:
            if any(cat.lower() in text for cat in rule["source_category"]):
                return _find_structure(structures, rule["structure"])
        if "default" in rule:
            return _find_structure(structures, rule["default"])

    return None


def _find_structure(structures: list[dict], name: str) -> dict | None:
    """Find a structure by name."""
    for s in structures:
        if s.get("name") == name:
            return s
    return None


# =====================================================================
# Japanese rejection reason translation
# =====================================================================

_REASON_MAP = {
    "citation_count": "引用数",
    "citation_format": "引用形式",
    "visual_count": "視覚要素数",
    "word_count": "文字数",
    "evidence_level": "エビデンスレベル",
    "heading_structure": "見出し構造",
    "forbidden_phrases": "禁止フレーズ",
    "chain_stores": "チェーン店検出",
    "no citations found": "引用なし",
    "no citation blocks or inline URLs found": "引用ブロックもURLもなし",
    "no visual elements found": "視覚要素なし",
    "citations found": "件の引用",
    "visual elements found": "件の視覚要素",
    "H2 headings": "個のH2見出し",
    "minimum 2 required": "最低2個必要",
    "minimum 3 required": "最低3個必要",
    "H1 should only be the title": "H1はタイトルのみ",
    "H1 heading(s) in body": "個のH1が本文中に存在",
    "only": "",
    "found": "",
    "range": "範囲",
}


def _extract_japanese_title(content: str) -> str:
    """Extract the Japanese article title from generated content.

    Priority order:
    1. First H1 ('# ') line
    2. First line starting with 【...】 or 「...」 (Gemma3 often places title this way)
    3. First H2 ('## ') that is NOT a section heading (導入, はじめに, etc.)
    4. First H2 fallback
    """
    if not content:
        return ""

    # Section heading words to skip (not actual titles)
    section_words = {
        "導入", "はじめに", "序章", "本編", "概要", "まとめ",
        "結論", "参考文献", "目次", "序文", "前書き",
    }

    lines = [line.strip() for line in content.split("\n") if line.strip()]

    # Priority 1: First H1
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            if title and not _is_mostly_ascii(title):
                return title[:100]

    # Priority 2: First line starting with 【 or 「 (Gemma3 title pattern)
    for line in lines[:3]:  # Only check first 3 lines
        if (line.startswith("【") or line.startswith("「")) and not _is_mostly_ascii(line):
            return line[:100]

    # Priority 3: First H2 that's NOT a section heading
    first_section_h2 = None
    for line in lines:
        if line.startswith("## "):
            title = line[3:].strip()
            # Remove leading bracket prefix for comparison
            clean = title.split("：", 1)[0].split(":", 1)[0].strip()
            if title and not _is_mostly_ascii(title):
                if clean not in section_words:
                    return title[:100]
                if first_section_h2 is None:
                    first_section_h2 = title

    # Priority 4: Fallback to first section H2 (better than English source)
    return (first_section_h2 or "")[:100]


def _is_mostly_ascii(text: str) -> bool:
    """Return True if the text has no Japanese characters (CJK/hiragana/katakana).

    Previous version counted numbers/symbols as ASCII, rejecting mixed
    titles like '2026年版 AI Agents 完全ガイド'. Now we check for the
    presence of any Japanese characters.
    """
    if not text:
        return True
    # Check for Japanese characters: hiragana, katakana, CJK ideographs
    for c in text:
        code = ord(c)
        # Hiragana: U+3040-U+309F
        # Katakana: U+30A0-U+30FF
        # CJK Unified Ideographs: U+4E00-U+9FFF
        # Katakana Phonetic Extensions: U+31F0-U+31FF
        # Half-width Katakana: U+FF65-U+FF9F
        if (
            0x3040 <= code <= 0x309F
            or 0x30A0 <= code <= 0x30FF
            or 0x4E00 <= code <= 0x9FFF
            or 0x31F0 <= code <= 0x31FF
            or 0xFF65 <= code <= 0xFF9F
        ):
            return False
    return True


def _translate_reasons(reasons_str: str) -> str:
    """Translate English rejection reasons to Japanese."""
    result = reasons_str
    for en, ja in _REASON_MAP.items():
        result = result.replace(en, ja)
    return result


# =====================================================================
# Markdown post-processing
# =====================================================================

_TITLE_BRACKETS: list[str] = [
    "殿堂入り記事", "殿堂記事", "殿堂入り記事・警告",
    "永久保存版", "保存版", "完全保存版", "警告・永久保存版", "決定版",
    "完全無料", "完全自動", "完全攻略", "完全ガイド", "完全まとめ",
    "速報", "最新", "2026年最新", "緊急", "号外", "現地レポ",
    "朝メモ", "夜メモ", "深夜便", "週末特集", "今月のベスト",
    "警告", "注意", "暴露", "本音", "リーク", "裏事情",
    "衝撃", "悲報", "朗報", "号泣", "絶句", "禁断",
    "入門", "必修", "コアメンバー", "プロが教える", "現場の声",
    "3分でわかる", "5選", "10の真実", "100人に聞いた", "99%が知らない",
    "ローカル限定", "穴場", "地元民だけが知る",
]


def _codex_research_brief(article: dict) -> str:
    """Run a Codex web-search research pass and return a prompt block.

    Only fires when the Codex CLI is available. On failure the block
    is empty so generation proceeds with the unchanged LLM-only path.
    The brief is injected at the end of the article prompt so Gemma3
    sees it as authoritative ground truth.
    """
    try:
        from utils.codex_researcher import CodexResearcher
        researcher = CodexResearcher()
        if not researcher.is_available():
            return ""
        area = _extract_area_hint(article)
        title = article.get("title", "")
        content = article.get("content", "")
        brief = researcher.research(
            source_title=title,
            source_content=content,
            area_hint=area,
        )
        if not brief.stores and not brief.summary:
            logger.info("[research] Codex returned empty brief")
            return ""
        verified = sum(1 for s in brief.stores if s.verified)
        logger.info(
            "[research] Codex brief: %d stores (%d verified)",
            len(brief.stores), verified,
        )
        return "\n\n" + brief.to_prompt_block()
    except Exception as exc:
        logger.warning("Codex research failed: %s", exc)
        return ""


def _pick_title_bracket_hint() -> str:
    """Return a short instruction pinning a random bracket for this run.

    The title-bracket list in prompts.yaml is explanatory; small local
    LLMs still collapse on a single favourite (【狂気】) unless a
    concrete choice is forced per run. This nudge picks one and
    instructs the model to use it verbatim, maximising variety across
    runs.
    """
    import random
    choice = random.choice(_TITLE_BRACKETS)
    return (
        f"\n\n【今回のタイトルブラケット指定】\n"
        f"この記事のタイトルの先頭は必ず「【{choice}】」で始めること。\n"
        f"他のブラケットは使用しないこと。同じ記事内で【狂気】等の別表現を重ねない。\n"
    )


_AI_DISCLAIMER_SENTINEL = "<!-- AI_DISCLAIMER -->"
_AI_DISCLAIMER_BLOCK = f"""
---

{_AI_DISCLAIMER_SENTINEL}
## ⚠️ 免責事項

本記事の店舗・施設情報は、執筆時点のGoogle Maps公開データおよび投稿情報をもとにAIが構成しています。営業時間・価格・メニュー等は変更される場合があるため、来店前に公式サイトまたは店舗へ直接ご確認ください。また、本記事は情報提供を目的としており、掲載情報の正確性・完全性を保証するものではありません。ご利用は読者ご自身の判断でお願いいたします。
"""


def _ensure_ai_disclaimer(content: str) -> str:
    """Append the AI-generated disclaimer if the LLM omitted it.

    Idempotent across re-runs (sentinel check) AND tolerant of the
    LLM authoring its own disclaimer block (heading-text check) so
    we never end up with two ⚠️免責事項 sections on one article.
    """
    if _AI_DISCLAIMER_SENTINEL in content:
        return content
    # LLM-authored disclaimers usually use "免責事項" as the H2.
    # Allow arbitrary chars (emoji + variation selectors) between ##
    # and 免責 so we don't end up with two disclaimer sections.
    if re.search(r"(?m)^#{1,3}.{0,6}免責", content):
        return content
    return content.rstrip() + "\n" + _AI_DISCLAIMER_BLOCK


def _extract_area_hint(article: dict) -> str:
    """Extract a locality keyword (e.g. "下北沢") from the source article.

    Order of precedence:
      1. ``article["query"]`` — set by BlueskyCollector, first token is
         the already-normalised area name (most trustworthy).
      2. Exact-match against the known-area list (same list the
         collector uses) scanned in title + content.
      3. Regex fallback for explicit locality suffixes (駅/区/市/町/村).
    """
    q = article.get("query") or ""
    if q:
        tokens = q.split()
        if tokens:
            return tokens[0]

    haystack = (article.get("title") or "") + " " + (article.get("content") or "")
    try:
        from collectors.bluesky_collector import (
            _TOKYO_AREAS, _KANAGAWA_AREAS, _SAITAMA_AREAS,
            _CHIBA_AREAS, _SHIZUOKA_AREAS,
        )
        for area in (
            _TOKYO_AREAS + _KANAGAWA_AREAS + _SAITAMA_AREAS
            + _CHIBA_AREAS + _SHIZUOKA_AREAS
        ):
            if area in haystack:
                return area
    except ImportError:
        pass

    m = re.search(
        r"([一-龥ぁ-んァ-ヴー]{2,6}(?:駅|区|市|町|村))",
        haystack,
    )
    return m.group(1) if m else ""


def _fix_markdown_structure(content: str) -> str:
    """Fix common Markdown structure issues from LLM output.

    - Convert lone H1 in body to H2
    - If fewer than 2 H2 headings, split long paragraphs with H2 headings
    - Ensure no H1 in body (only title)
    """
    lines = content.split("\n")
    result = []
    h2_count = 0

    for line in lines:
        # Convert ALL H1 in body to H2 (H1 is reserved for article title only)
        stripped = line.lstrip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            result.append(line.replace("# ", "## ", 1))
            h2_count += 1
        elif line.startswith("## "):
            h2_count += 1
            result.append(line)
        else:
            result.append(line)

    # NOTE: Do NOT auto-inject H2 headings.
    # Gemma3 sometimes generates H3 headings with numbers (### 1. XXX).
    # Injecting "## 概要" etc at arbitrary positions breaks the flow.
    # Better to rely on prompt enforcement + H1→H2 conversion only.

    return "\n".join(result)


# =====================================================================
# Stock image insertion (Unsplash / Pexels)
# =====================================================================

# Cache results across calls within a single process to avoid repeat API hits.
_STOCK_IMAGE_CACHE: dict[str, list[dict]] = {}

# Japanese particles / stop tokens to strip when extracting keywords.
_JP_STOPWORDS = frozenset({
    "の", "が", "を", "は", "に", "へ", "と", "で", "や", "も", "から",
    "まで", "より", "こと", "もの", "これ", "それ", "あれ", "する",
    "した", "して", "いる", "ある", "なる", "という", "ため", "ように",
    "とは", "とき", "なら", "ば", "ね", "よ", "か",
})


_THEME_KEYWORDS: list[tuple[str, str]] = [
    ("コーヒー", "coffee"), ("カフェ", "cafe"), ("ランチ", "restaurant food"),
    ("居酒屋", "izakaya japanese bar"), ("グルメ", "food"),
    ("ラーメン", "ramen"), ("寿司", "sushi"), ("スイーツ", "dessert"),
    ("韓国", "korea seoul"), ("美容", "beauty cosmetics"),
    ("コスメ", "cosmetics"), ("ファッション", "fashion"),
    ("旅行", "travel"), ("観光", "travel landmark"),
    ("AI", "artificial intelligence"), ("LLM", "ai technology"),
    ("Claude", "ai technology"), ("ChatGPT", "ai technology"),
    ("Python", "python code"), ("React", "web development"),
    ("論文", "research paper"), ("機械学習", "machine learning"),
    ("投資", "finance investment"), ("副業", "business laptop"),
    ("マネタイズ", "business money"), ("起業", "startup"),
]


def _extract_image_query(title: str) -> str:
    """Extract a short English-friendly search query from a Japanese title.

    Strategy:
      1. Match known Japanese theme keywords → map to English terms
         (best signal for image search).
      2. Extract any ASCII alphanumeric runs (e.g. "Claude", "LLM").
      3. Fallback to a hard-coded generic term.

    Unsplash/Pexels handle English far better than Japanese and outright
    reject very long queries, so we cap at ~3 short tokens.
    """
    if not title:
        return "technology"

    keywords: list[str] = []

    # 1. Theme keyword mapping — most reliable.
    for jp, en in _THEME_KEYWORDS:
        if jp.lower() in title.lower() and en not in keywords:
            keywords.append(en)
            if len(keywords) >= 2:
                break

    # 2. Pull out ASCII tokens (product names, acronyms).
    for m in re.findall(r"[A-Za-z][A-Za-z0-9+]{1,14}", title):
        if m.lower() in {"http", "https", "www", "com"}:
            continue
        if m not in keywords:
            keywords.append(m)
        if len(keywords) >= 3:
            break

    if keywords:
        return " ".join(keywords[:3])

    # 3. Fallback: generic term based on rough domain guess.
    if any(w in title for w in ("AI", "ＡＩ", "LLM", "モデル", "論文")):
        return "technology ai"
    if any(w in title for w in ("店", "グルメ", "食", "メニュー")):
        return "food restaurant"
    return "lifestyle"


def _download_image(url: str, dest: Path) -> Path | None:
    """Download an image from a URL to a local destination.

    Returns the destination path on success, ``None`` on failure.
    """
    if not url:
        return None
    try:
        import requests as _requests
        resp = _requests.get(url, timeout=30)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest
    except Exception as exc:
        logger.warning("Image download failed (%s): %s", url, exc)
        return None


def _fetch_cached_images(sourcer, query: str, count: int) -> list[dict]:
    """Fetch images from ImageSourcer with per-process caching."""
    cache_key = f"{query}::{count}"
    if cache_key in _STOCK_IMAGE_CACHE:
        return _STOCK_IMAGE_CACHE[cache_key]
    try:
        results = sourcer.find_images(query, count=count)
    except Exception as exc:
        logger.warning("ImageSourcer.find_images failed: %s", exc)
        results = []
    _STOCK_IMAGE_CACHE[cache_key] = results
    return results


def _build_stock_image_block(image: dict, local_path: Path, alt: str) -> str:
    """Build a Markdown image block (no attribution caption)."""
    rel = local_path.as_posix()
    if "data/images/" not in rel:
        rel = f"data/images/stock/{local_path.name}"
    safe_alt = alt.replace("[", "(").replace("]", ")")
    return f"![{safe_alt}]({rel})\n"


def _insert_stock_images(
    content: str,
    title: str,
    sourcer,
    slug: str,
    section_count: int = 2,
) -> str:
    """Fetch stock photos and insert them into the article markdown.

    Hero image: inserted right after the first H2 (or at top if no H2).
    Section images: inserted before every 2nd subsequent H2.

    Failures are swallowed; the original content is returned unchanged.
    """
    if not content or not title:
        return content

    query = _extract_image_query(title)
    total_needed = 1 + section_count
    images = _fetch_cached_images(sourcer, query, total_needed)

    # Filter out placeholder/empty results
    usable = [img for img in images if img.get("url") and img.get("platform") != "Placeholder"]
    if not usable:
        logger.info("[image] No usable stock images for query '%s' — skipping.", query)
        return content

    stock_dir = Path("data/images/stock")
    stock_dir.mkdir(parents=True, exist_ok=True)

    # Download images locally
    downloaded: list[tuple[dict, Path]] = []
    for idx, img in enumerate(usable):
        ext = ".jpg"
        # Hash query+source for stable filenames (cache reuse)
        safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)[:40]
        filename = f"{safe_slug}_{idx}{ext}"
        dest = stock_dir / filename
        if dest.exists() and dest.stat().st_size > 0:
            downloaded.append((img, dest))
            continue
        url = img.get("url") or img.get("download_url", "")
        local = _download_image(url, dest)
        if local is not None:
            downloaded.append((img, local))

    if not downloaded:
        return content

    # Build hero image block
    hero_img, hero_path = downloaded[0]
    hero_alt = hero_img.get("alt_text") or title
    hero_block = _build_stock_image_block(hero_img, hero_path, hero_alt)

    section_blocks = [
        _build_stock_image_block(img, path, img.get("alt_text") or title)
        for img, path in downloaded[1:]
    ]

    # Insert into markdown
    lines = content.split("\n")
    out: list[str] = []
    h2_seen = 0
    hero_inserted = False
    section_idx = 0

    for line in lines:
        is_h2 = line.startswith("## ")
        if is_h2:
            h2_seen += 1
            # Insert section image BEFORE every 2nd H2 (but not the first)
            if h2_seen >= 3 and (h2_seen % 2) == 1 and section_idx < len(section_blocks):
                out.append("")
                out.append(section_blocks[section_idx])
                section_idx += 1
            out.append(line)
            # Insert hero image AFTER first H2
            if not hero_inserted and h2_seen == 1:
                out.append("")
                out.append(hero_block)
                hero_inserted = True
        else:
            out.append(line)

    # If no H2 found at all, prepend hero at the top
    if not hero_inserted:
        out = [hero_block, ""] + out

    return "\n".join(out)


# =====================================================================
# Config
# =====================================================================

def _default_config() -> dict:
    """Return sensible defaults when settings.yaml is absent."""
    return {
        "collection": {
            "zenn": {"sources": ["arxiv"], "max_articles": 10},
            "note": {"sources": ["reddit"], "max_articles": 20},
        },
        "generation": {
            "zenn": {"articles_per_week": 1, "min_quality_score": 60},
            "note": {"articles_per_week": 1, "min_quality_score": 45},
        },
        "token_management": {"weekly_limit": 2000000},
        "evidence": {"forbidden_phrases": []},
    }


def load_config(config_path: str = "config/settings.yaml") -> dict:
    """設定ファイルを読み込む。"""
    path = Path(config_path)
    if not path.exists():
        logger.warning(
            "%s not found. Using default configuration.", config_path
        )
        return _default_config()
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prompts(prompts_path: str = "config/prompts.yaml") -> dict:
    """プロンプトテンプレートを読み込む。"""
    path = Path(prompts_path)
    if not path.exists():
        logger.warning("%s not found. Using empty prompts.", prompts_path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# =====================================================================
# Phase 1: 収集
# =====================================================================

def collect_articles(config: dict) -> dict:
    """各ソースから記事を収集する。"""
    logger.info("=== Phase 1: 記事収集 ===")
    collected = {"zenn": [], "note": []}

    try:
        arxiv = ArxivCollector(
            max_results=config.get("collection", {}).get(
                "zenn", {}
            ).get("max_articles", 10)
        )
        articles = arxiv.collect()
        collected["zenn"].extend(articles)
        logger.info("arXiv: %d件収集", len(articles))
    except Exception as e:
        logger.error("arXiv収集エラー: %s", e)

    try:
        reddit = RedditCollector(
            max_results=config.get("collection", {}).get(
                "note", {}
            ).get("max_articles", 20)
        )
        articles = reddit.collect()
        collected["note"].extend(articles)
        logger.info("Reddit: %d件収集", len(articles))
    except Exception as e:
        logger.error("Reddit収集エラー: %s", e)

    # 日本語ソース（RSS）
    try:
        rss_zenn = RssCollector(target_platform="zenn", max_results=10)
        articles = rss_zenn.collect()
        collected["zenn"].extend(articles)
        logger.info("RSS(Zenn向け): %d件収集", len(articles))
    except Exception as e:
        logger.error("RSS(Zenn)収集エラー: %s", e)

    try:
        rss_note = RssCollector(target_platform="note", max_results=10)
        articles = rss_note.collect()
        collected["note"].extend(articles)
        logger.info("RSS(note向け): %d件収集", len(articles))
    except Exception as e:
        logger.error("RSS(note)収集エラー: %s", e)

    # Bluesky: hyper-local / niche gourmet / lifestyle posts for note
    try:
        bsky_cfg = config.get("collection", {}).get("bluesky", {}) or {}
        bsky = BlueskyCollector(
            queries=bsky_cfg.get("queries") or None,
            min_likes=bsky_cfg.get("min_likes", 2),
            limit_per_query=bsky_cfg.get("limit_per_query", 25),
            max_results=bsky_cfg.get("max_results", 30),
        )
        articles = bsky.collect()
        collected["note"].extend(articles)
        logger.info("Bluesky: %d件収集", len(articles))
    except Exception as e:
        logger.error("Bluesky収集エラー: %s", e)

    return collected


def rank_articles(collected: dict) -> dict:
    """トレンドスコアで記事をランク付けする。"""
    logger.info("=== トレンドスコア計算 ===")
    detector = TrendDetector()
    ranked = {}
    for platform, articles in collected.items():
        ranked[platform] = detector.rank_articles(articles)
        if ranked[platform]:
            top = ranked[platform][0]
            logger.info(
                "%s トップ: %s (スコア: %.1f)",
                platform, top["title"][:40], top.get("trend_score", 0)
            )
    return ranked


# =====================================================================
# Phase 2: 生成 + スコアリング
# =====================================================================

def _init_llm(token_manager: TokenManager):
    """LLMバックエンドを初期化する。(claude or local)"""
    local_llm = LocalLLM()
    use_local = not token_manager.is_within_budget()

    if use_local:
        logger.warning("トークン予算超過。ローカルLLMにフォールバック。")
        if not local_llm.is_available():
            logger.error("ローカルLLMも利用不可。")
            return None, None, True
        return None, local_llm, True

    # Claude.ai Selenium is disabled (Cloudflare bot detection blocks it).
    # Use local LLM (Gemma3) for all generation.
    if not local_llm.is_available():
        logger.error("ローカルLLM (Ollama) 未起動。ollama serve を実行してください。")
        return None, None, True
    logger.info("ローカルLLM (Gemma3) で記事生成します。")
    return None, local_llm, True


def _generate_single_article(
    article: dict,
    platform: str,
    template: str,
    claude,
    local_llm: LocalLLM,
    use_local: bool,
    token_manager: TokenManager,
    config: dict,
    prompts: dict | None = None,
) -> dict | None:
    """1記事を生成し、2層スコアリングを行う。

    Returns:
        スコアリング済み記事dict (with "rejected" key if failed),
        or None on generation failure.
    """
    # --- 構成パターン選択 ---
    structure = _select_structure(
        article.get("title", ""),
        article.get("source", ""),
        platform,
        prompts,
    )
    structure_name = "standard"
    structure_instruction = ""
    if structure:
        structure_name = structure.get("name", "standard")
        structure_instruction = (
            f"\n\n【構成パターン: {structure.get('description', '')}】\n"
            f"以下の構成に従って記事を書いてください:\n"
            f"{structure.get('outline', '')}"
        )
        logger.info("[%s] 構成パターン: %s", platform, structure_name)

    # Runtime bracket rotation: pick one title bracket at random so
    # the LLM does not keep defaulting to 【狂気】 / 【永久保存版】.
    bracket_hint = _pick_title_bracket_hint()

    # Pre-generation research pass: delegate web search to Codex CLI
    # so Gemma3 has a grounded fact brief to cite from. Only for note
    # — Zenn tech articles are research-light.
    research_block = ""
    if platform == "note":
        research_block = _codex_research_brief(article)

    # --- 生成 ---
    try:
        prompt = (
            template.format(**article)
            + structure_instruction
            + bracket_hint
            + research_block
        )
    except KeyError as e:
        logger.warning("プロンプトテンプレートのキー不足: %s", e)
        return None

    if use_local:
        content = local_llm.generate(prompt)
    else:
        content = claude.generate_article(template, article)
    token_manager.record_usage(
        estimate_tokens(prompt) + estimate_tokens(content)
    )

    # --- Markdown構造補正（Gemma3が見出しを省略する問題の対策） ---
    content = _fix_markdown_structure(content)

    # --- Google Places API によるスポット検証（note グルメ/地域記事のみ） ---
    # LLMが書いた店名を Google Places で検証し、実在しない店は丸ごと削除、
    # 実在する店は住所/営業時間/価格/公式URL を Places の正式データで上書き。
    if platform == "note":
        try:
            from utils.places_verifier import PlacesVerifier
            _verifier = PlacesVerifier()
            # Always call verify_and_fill — it is a no-op when the
            # content has no STORE_BLOCK sentinels, and runs in
            # fail-closed scrub mode when the API key is missing.
            area_hint = _extract_area_hint(article)
            content, _places_stats = _verifier.verify_and_fill(
                content, area_hint=area_hint
            )
            if any(_places_stats.values()):
                logger.info(
                    "[note] Places検証: verified=%d dropped=%d chain=%d scrubbed=%d (area=%s)",
                    _places_stats["verified"],
                    _places_stats["dropped"],
                    _places_stats["chain_filtered"],
                    _places_stats.get("scrubbed", 0),
                    area_hint or "-",
                )
        except Exception as exc:
            logger.warning("Places検証失敗: %s", exc)

        # URL hygiene: shorten duplicated anchors and strip
        # hallucinated bare URLs that point to domains we do not trust.
        try:
            from utils.url_cleaner import clean_article_urls
            content = clean_article_urls(content)
        except Exception as exc:
            logger.warning("URL cleaner failed: %s", exc)

        # Guarantee the AI-disclosure footer even when the LLM omits it.
        content = _ensure_ai_disclaimer(content)

    # --- アフィリエイトリンク自動挿入 ---
    try:
        from generators.affiliate_injector import AffiliateInjector
        _aff = AffiliateInjector()
        content = _aff.inject(content, title=article.get("title", ""), platform=platform)
    except Exception as exc:
        logger.warning("アフィリエイト挿入失敗: %s", exc)

    # --- slug生成（図表処理・スコアリングで使用） ---
    _safe_title = re.sub(r'[\\/:*?"<>|]', '_', article.get('title', 'untitled')[:20])
    slug = f"{platform}-{_safe_title}"

    # --- ストック画像挿入（Unsplash / Pexels） ---
    # noteは特に画像が無いと見栄えが悪いので両プラットフォームで挿入。
    try:
        from generators.image_sourcer import ImageSourcer
        _sourcer = ImageSourcer()
        # noteは多めに、zennは控えめに
        _sec = 3 if platform == "note" else 1
        content = _insert_stock_images(
            content, article.get("title", ""), _sourcer, slug, section_count=_sec
        )
    except Exception as exc:
        logger.warning("画像挿入失敗: %s", exc)

    # --- 図表処理 ---
    diagram_gen = DiagramGenerator()
    content = diagram_gen.embed_diagrams(content, "docs/images", base_name=slug)

    # --- 客観スコア ---
    evidence_mgr = EvidenceManager()
    forbidden = config.get("evidence", {}).get("forbidden_phrases", [])
    sources = article.get("sources", [])

    chain_blacklist = config.get("evidence", {}).get(
        "gourmet_rules", {}
    ).get("chain_blacklist", [])

    obj_scorer = ObjectiveScorer()
    obj_result = obj_scorer.score(content, {
        "sources": sources,
        "forbidden_phrases": forbidden,
        "chain_blacklist": chain_blacklist,
    })

    if not obj_result["objective_pass"]:
        logger.info(
            "[%s] 客観スコア不合格: %s — %s",
            platform, article["title"][:30], obj_result["blocking_issues"]
        )
        return {
            "rejected": True,
            "title": article["title"],
            "platform": platform,
            "content": content,
            "rejection_reasons": _translate_reasons("; ".join(obj_result["blocking_issues"])),
            "rejection_stage": "客観スコア",
        }

    # --- 主観スコア ---
    eval_fn = (
        local_llm.generate if use_local
        else lambda p: claude.send_prompt(p)
    )
    subj_evaluator = SubjectiveEvaluator()
    subj_result = subj_evaluator.score(content, eval_fn, {
        "research_brief": article.get("content", ""),
    })
    token_manager.record_usage(estimate_tokens(content))

    # --- 集約判定 ---
    aggregator = ScoreAggregator()
    final = aggregator.aggregate(
        obj_result,
        subj_result,
        context={
            "slug": slug,
            "title": article["title"],
            "platform": platform,
        },
    )

    if final["decision"] == "reject":
        logger.info(
            "[%s] 総合C却下: %s — %s",
            platform, article["title"][:30], final["summary"]
        )
        return {
            "rejected": True,
            "title": article["title"],
            "platform": platform,
            "content": content,
            "rejection_reasons": _translate_reasons(final.get("summary", "総合評価で却下")),
            "rejection_stage": "総合評価",
        }

    # --- カバー画像生成 ---
    cover_gen = CoverGenerator()
    cover_path = cover_gen.generate(
        title=article["title"],
        platform=platform,
        slug=slug,
    )

    logger.info(
        "[%s] 生成完了: %s (総合: %s, 証拠Lv: %s)",
        platform,
        article["title"][:30],
        final["overall_grade"],
        final["evidence_level"],
    )

    # Save article content for later --publish retrieval
    store = ArticleStore()
    store.save(slug, {
        "title": article["title"],
        "content": content,
        "platform": platform,
        "source": article,
        "cover_image": cover_path,
        "scores": final,
    })

    return {
        "title": article["title"],
        "content": content,
        "source": article,
        "platform": platform,
        "slug": slug,
        "cover_image": cover_path,
        "structure_type": structure_name,
        "scores": final,
        "generated_at": datetime.now().isoformat(),
    }


def _load_generated_sources() -> set[str]:
    """Load URLs of sources already used for article generation."""
    path = Path("data/generated_sources.json")
    if path.exists():
        try:
            import json
            return set(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_generated_source(url: str) -> None:
    """Record a source URL as used for generation."""
    path = Path("data/generated_sources.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    import json
    existing = _load_generated_sources()
    existing.add(url)
    # Cap at 500 entries
    if len(existing) > 500:
        existing = set(list(existing)[-250:])
    path.write_text(json.dumps(list(existing), ensure_ascii=False), encoding="utf-8")


def generate_and_score(
    ranked: dict,
    config: dict,
    prompts: dict,
    token_manager: TokenManager,
) -> tuple[list[dict], list[dict]]:
    """記事を生成し、2層スコアリングで評価する。

    Returns:
        Tuple of (approved articles list, rejected articles list).
        Approved = grade A/B. Rejected = grade C with content & reasons.
    """
    logger.info("=== Phase 2: 生成 + スコアリング ===")
    claude, local_llm, use_local = _init_llm(token_manager)
    if local_llm is None and claude is None:
        return [], []

    generated_sources = _load_generated_sources()
    approved = []
    rejected = []

    for platform in ["zenn", "note"]:
        template = prompts.get(f"{platform}_article_prompt", "")
        articles_per_week = config.get("generation", {}).get(
            platform, {}
        ).get("articles_per_week", 1)

        # Filter out already-used sources, then take top N
        candidates = [
            a for a in ranked.get(platform, [])
            if a.get("url", "") not in generated_sources
        ]
        if len(candidates) < len(ranked.get(platform, [])):
            skipped = len(ranked.get(platform, [])) - len(candidates)
            logger.info("[%s] 生成済みソースをスキップ: %d件", platform, skipped)

        # note: Blueskyのローカル/グルメ系ソースを1枠予約する。
        # Bluesky posts rank lower than Reddit by raw social signal,
        # but niche locality content is the whole point of including
        # Bluesky, so we guarantee one slot for it when available.
        selection = candidates[:articles_per_week]
        if platform == "note":
            top_bluesky = next(
                (a for a in candidates if a.get("source") == "bluesky"),
                None,
            )
            if top_bluesky and top_bluesky not in selection:
                # Replace the lowest-ranked pick with the Bluesky one.
                if selection:
                    selection[-1] = top_bluesky
                else:
                    selection = [top_bluesky]
                logger.info(
                    "[note] Bluesky枠を確保: %s",
                    top_bluesky.get("title", "")[:40],
                )

        for article in selection:
            try:
                result = _generate_single_article(
                    article, platform, template,
                    claude, local_llm, use_local,
                    token_manager, config, prompts,
                )
                # Record source as used regardless of result
                source_url = article.get("url", "")
                if source_url:
                    _save_generated_source(source_url)

                if result is None:
                    pass
                elif result.get("rejected"):
                    rejected.append(result)
                else:
                    approved.append(result)
            except Exception as e:
                logger.error(
                    "[%s] 生成エラー (%s): %s",
                    platform, article.get("title", "?")[:30], e
                )

    if claude:
        claude.close()

    return approved, rejected


# =====================================================================
# Rejected article handling
# =====================================================================

def _post_rejected_to_slack(rejected: list[dict]) -> None:
    """Post rejected article content to Slack as file attachments."""
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = os.getenv("SLACK_CHANNEL_ID", "C0AR7E9AFJ9")
    if not bot_token:
        logger.warning("SLACK_BOT_TOKEN not set; skipping rejected article Slack upload")
        return

    try:
        from slack_sdk import WebClient
        client = WebClient(token=bot_token)
    except ImportError:
        logger.warning("slack_sdk not installed; skipping rejected article Slack upload")
        return

    # Load already-posted titles to avoid duplicate Slack messages
    posted_path = Path("data/rejected_posted.json")
    posted_titles: set[str] = set()
    if posted_path.exists():
        try:
            import json as _json
            posted_titles = set(_json.loads(posted_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    new_posted = []
    for article in rejected:
        title = article.get("title", "untitled")
        if title in posted_titles:
            logger.info("Slack送信スキップ（送信済み）: %s", title[:40])
            continue

        platform = article.get("platform", "?")
        reasons = article.get("rejection_reasons", "unknown")
        content = article.get("content", "")
        stage = article.get("rejection_stage", "unknown")

        filename = re.sub(r'[\\/:*?"<>|]', '_', title[:40]) + ".md"
        comment = (
            f":x: *不合格記事*: {title}\n"
            f"*プラットフォーム*: {platform}\n"
            f"*却下段階*: {stage}\n"
            f"*理由*: {reasons}"
        )

        try:
            client.files_upload_v2(
                channel=channel_id,
                content=content,
                filename=filename,
                title=f"[不合格] {title[:80]}",
                initial_comment=comment,
            )
            logger.info("Slack uploaded rejected article: %s", title[:40])
            new_posted.append(title)
        except Exception as e:
            logger.error("Slack file upload failed for '%s': %s", title[:30], e)

    # Save posted titles
    if new_posted:
        import json as _json
        posted_titles.update(new_posted)
        if len(posted_titles) > 200:
            posted_titles = set(list(posted_titles)[-100:])
        posted_path.parent.mkdir(parents=True, exist_ok=True)
        posted_path.write_text(
            _json.dumps(list(posted_titles), ensure_ascii=False), encoding="utf-8"
        )


def _save_rejected_articles(
    rejected: list[dict],
    sheets: SheetsManager,
) -> None:
    """Save rejected articles to the '不合格' sheet and post to Slack."""
    if not rejected:
        return

    logger.info("不合格記事を保存: %d件", len(rejected))
    now = datetime.now().isoformat()

    for article in rejected:
        sheets.add_rejected_article({
            "title": article.get("title", ""),
            "platform": article.get("platform", ""),
            "rejection_reasons": article.get("rejection_reasons", ""),
            "timestamp": now,
            "content": article.get("content", ""),
        })

    _post_rejected_to_slack(rejected)


# =====================================================================
# Phase 3: Sheets登録 + Gmail通知（承認待ち）
# =====================================================================

def register_for_approval(
    articles: list[dict],
    sheets: SheetsManager,
    gmail: GmailNotifier,
) -> None:
    """合格記事をSheetsに登録し、Gmailで通知する。"""
    if not articles:
        logger.info("承認待ち記事なし。")
        return

    logger.info("=== Phase 3: Sheets登録 + Gmail通知 ===")

    for article in articles:
        sheets_data = article["scores"].get("for_sheets", {})
        if not sheets_data:
            sheets_data = {
                "article_id": article.get("slug", ""),
                "title": article["title"],
                "status": "⏳承認待ち",
                "evidence_level": article["scores"].get(
                    "evidence_level", "-"
                ),
                "overall_grade": article["scores"].get(
                    "overall_grade", "-"
                ),
                "platform": article.get("platform", ""),
                "critic_summary": article["scores"].get("summary", ""),
            }
        sheets.add_article(sheets_data)
        logger.info("Sheets登録: %s", article["title"][:40])

    # Gmail通知
    sheets_url = os.getenv("GOOGLE_SHEET_URL", "")
    gmail_articles = []
    for a in articles:
        gmail_articles.append({
            "title": a["title"],
            "overall_grade": a["scores"].get("overall_grade", "-"),
            "evidence_level": a["scores"].get("evidence_level", "-"),
            "tier12_ratio": a["scores"].get(
                "objective_detail", {}
            ).get(
                "evidence_level", {}
            ).get("tier12_ratio", 0),
        })
    gmail.notify_pending_approval(gmail_articles, sheets_url)
    logger.info("Gmail通知送信: %d件の承認待ち", len(articles))


# =====================================================================
# Phase 4: 承認済み記事の投稿
# =====================================================================

def publish_approved(
    sheets: SheetsManager,
    config: dict,
    slack: SlackNotifier,
    gmail: GmailNotifier,
    feedback: FeedbackRecorder,
) -> dict:
    """Sheetsで「✅承認」された記事を投稿する。"""
    logger.info("=== Phase 4: 承認済み記事の投稿 ===")
    results = {"zenn": [], "note": []}

    approved = sheets.get_approved_articles()
    if not approved:
        logger.info("承認済み記事なし。")
        return results

    for article_data in approved:
        platform = article_data.get("platform", "")
        title = article_data.get("title", "")
        article_id = article_data.get("article_id", "")

        # Load persisted article content from local store
        store = ArticleStore()
        stored = store.load(article_id)
        if not stored:
            logger.error("記事コンテンツが見つかりません: %s", article_id)
            continue
        content = stored.get("content", "")
        source = stored.get("source", "")

        # Extract Japanese title from content H1/H2 if original is English
        jp_title = _extract_japanese_title(content) or title
        if jp_title != title:
            logger.info("日本語タイトル抽出: %s", jp_title[:50])
            title = jp_title

        try:
            if platform == "zenn":
                scores = stored.get("scores", {})
                numeric_score = float(scores.get("numeric_score") or 0)
                # Threshold: 82.5 — below this a full article feels
                # undercooked, so fall back to Zenn Scraps which are
                # explicitly framed as rough notes.
                if numeric_score >= 82.5:
                    logger.info(
                        "[zenn] score=%.1f >= 82.5 → 記事投稿",
                        numeric_score,
                    )
                    url = _publish_zenn(article_id, title, content, stored)
                else:
                    logger.info(
                        "[zenn] score=%.1f < 82.5 → スクラップ投稿",
                        numeric_score,
                    )
                    url = _save_scrap_draft(article_id, title, content, stored)
            elif platform == "note":
                # 本人情報登録を回避するため当面は全記事無料公開
                url = _publish_note(title, content, config, source=str(source), price=0)
            else:
                logger.warning("不明なplatform: %s", platform)
                continue

            if url:
                results[platform].append(title)
                sheets.update_status(article_id, "✅投稿済み")
                slack.notify_published(platform, title, url)
                gmail.notify_published(platform, title, url)
                feedback.record_publish(
                    platform=platform,
                    title=title,
                    url=url,
                    quality_score=0,
                    structure_type=article_data.get(
                        "structure_type", "standard"
                    ),
                )
                logger.info("[%s] 投稿完了: %s", platform, title[:40])

        except Exception as e:
            logger.error("[%s] 投稿エラー: %s — %s", platform, title[:30], e)
            slack.notify_error(str(e), f"{platform}: {title[:30]}")
            gmail.notify_error(str(e), f"{platform}: {title[:30]}")

    return results


def _save_scrap_draft(
    slug: str, title: str, content: str, stored: dict
) -> str | None:
    """Grade B記事をZennスクラップとして自動投稿 + バックアップ保存.

    Playwrightでzenn.devにログイン済みの場合は自動投稿。
    失敗時は下書きファイル保存 + Slackに通知（手動投稿用）。
    """
    scrap_dir = Path("data/scraps")
    scrap_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = re.sub(r'[\\/:*?"<>|]', '_', slug)[:100]
    file_path = scrap_dir / f"{safe_slug}.md"

    grade = stored.get("scores", {}).get("overall_grade", "B")

    # Always save a local backup
    file_path.write_text(content, encoding="utf-8")
    logger.info("スクラップ下書き保存: %s", file_path)

    # Try auto-publishing via Playwright
    auto_url = None
    try:
        from publishers.zenn_scrap_publisher import ZennScrapPublisher
        with ZennScrapPublisher(headless=True) as pub:
            auto_url = pub.publish_scrap(title=title, content=content)
        logger.info("Zennスクラップ自動投稿成功: %s", auto_url)
    except Exception as e:
        logger.warning("Zennスクラップ自動投稿失敗: %s", e)
        auto_url = None

    # Slack notification
    try:
        bot_token = os.getenv("SLACK_BOT_TOKEN")
        channel_id = os.getenv("SLACK_CHANNEL_ID", "C0AR7E9AFJ9")
        if bot_token:
            from slack_sdk import WebClient
            client = WebClient(token=bot_token)
            if auto_url:
                client.chat_postMessage(
                    channel=channel_id,
                    text=(
                        f"📋 *スクラップ自動投稿完了* (Grade {grade})\n"
                        f"*タイトル*: {title}\n"
                        f"*URL*: {auto_url}"
                    ),
                )
            else:
                client.files_upload_v2(
                    channel=channel_id,
                    content=content,
                    filename=f"{safe_slug}.md",
                    title=f"[スクラップ] {title[:80]}",
                    initial_comment=(
                        f"📋 *スクラップ候補* (Grade {grade}) - 自動投稿失敗\n"
                        f"*タイトル*: {title}\n"
                        f"https://zenn.dev/scraps/new にコピペしてください"
                    ),
                )
    except Exception as e:
        logger.warning("Slack scrap notify failed: %s", e)

    return auto_url or f"scrap-draft:{file_path}"


def _publish_zenn(
    slug: str, title: str, content: str, stored: dict
) -> str | None:
    """Zenn記事を投稿する。"""
    zenn_repo = os.getenv("ZENN_REPO_PATH")
    if not zenn_repo:
        logger.warning("ZENN_REPO_PATH未設定。Zenn投稿スキップ。")
        return None
    publisher = ZennPublisher(zenn_repo)

    # Create the article file if it doesn't exist yet
    source = stored.get("source", {})
    topics = []
    if isinstance(source, dict):
        topics = source.get("topics", source.get("tags", []))
    if not topics:
        topics = ["ai", "tech"]

    zenn_slug = publisher.create_article(
        title=title,
        content=content,
        topics=topics[:5],
        article_type="tech",
    )
    success = publisher.publish(zenn_slug)
    if success:
        zenn_user = os.getenv("ZENN_USERNAME", "kento_cell")
        return f"https://zenn.dev/{zenn_user}/articles/{zenn_slug}"
    return None


def _publish_note(
    title: str, content: str, config: dict, source: str = "", price: int = 0
) -> str | None:
    """note記事を投稿する（ハッシュタグ自動生成付き）。"""
    note_pub = None
    try:
        note_pub = NotePublisher()

        # ハッシュタグ自動生成
        hashtag_gen = HashtagGenerator(max_tags=10)
        tags = hashtag_gen.generate(
            title=title,
            content=content,
            source=source,
        )
        if not tags:
            tags = ["AI", "テクノロジー", "トレンド"]
        logger.info("note ハッシュタグ: %s", tags)

        url = note_pub.publish_article(
            title=title,
            content=content,
            tags=tags,
            price=price,
        )
        return url
    except Exception as e:
        logger.error("note投稿失敗: %s", e)
        return None
    finally:
        if note_pub:
            note_pub.close()


# =====================================================================
# Regeneration pipeline
# =====================================================================

def _process_regeneration_requests(
    regen_requests: list[dict],
    sheets: SheetsManager,
    slack: SlackNotifier,
    gmail: GmailNotifier,
    config: dict,
    token_manager: TokenManager,
) -> None:
    """Process regeneration requests using multi-agent pipeline.

    For each request:
    1. Load stored article from ArticleStore
    2. Run Regenerator.regenerate()
    3. Run objective + subjective scoring
    4. If pass, register for approval; if fail, save to rejected
    5. Post progress to Slack
    """
    _, local_llm, use_local = _init_llm(token_manager)
    if local_llm is None:
        logger.error("LLM not available for regeneration.")
        return

    regenerator = Regenerator(local_llm)
    store = ArticleStore()
    obj_scorer = ObjectiveScorer()

    for req in regen_requests:
        article_id = req.get("article_id", "")
        title = req.get("title", "?")
        platform = req.get("platform", "")
        logger.info("再生成開始: %s (article_id=%s)", title[:40], article_id)

        # Note: keep status as 🔄再生成 during processing (it's an allowed dropdown value)

        # Load stored article
        stored = store.load(article_id)
        if not stored:
            logger.error("記事が見つかりません: %s", article_id)
            try:
                sheets.update_status(article_id, "❌却下")
            except Exception:
                pass
            continue

        # Run regeneration pipeline
        try:
            regen_result = regenerator.regenerate(stored)
        except Exception as e:
            logger.error("再生成エラー (%s): %s", title[:30], e)
            try:
                sheets.update_status(article_id, "🔄再生成")
            except Exception:
                pass
            slack.notify_error(
                str(e), f"再生成失敗: {title[:30]}",
            )
            continue

        if regen_result.get("error"):
            logger.error(
                "再生成失敗 (%s): %s", title[:30], regen_result["error"],
            )
            try:
                sheets.update_status(article_id, "🔄再生成")
            except Exception:
                pass
            slack.notify_error(
                regen_result["error"], f"再生成失敗: {title[:30]}",
            )
            continue

        content = regen_result.get("content", "")
        if not content:
            logger.error("再生成結果が空: %s", title[:30])
            try:
                sheets.update_status(article_id, "🔄再生成")
            except Exception:
                pass
            continue

        # Run objective scoring on regenerated content
        forbidden = config.get("evidence", {}).get("forbidden_phrases", [])
        sources = stored.get("source", {})
        if isinstance(sources, dict):
            sources = sources.get("sources", [])
        else:
            sources = []

        chain_blacklist = config.get("evidence", {}).get(
            "gourmet_rules", {},
        ).get("chain_blacklist", [])

        obj_result = obj_scorer.score(content, {
            "sources": sources,
            "forbidden_phrases": forbidden,
            "chain_blacklist": chain_blacklist,
        })

        # Run subjective scoring
        eval_fn = local_llm.generate
        subj_evaluator = SubjectiveEvaluator()
        subj_result = subj_evaluator.score(content, eval_fn, {
            "research_brief": "",
        })
        token_manager.record_usage(estimate_tokens(content) * 2)

        # Aggregate scores
        aggregator = ScoreAggregator()
        regen_title = regen_result.get("title", title)
        slug = article_id  # Keep the same article_id/slug
        final = aggregator.aggregate(
            obj_result,
            subj_result,
            context={
                "slug": slug,
                "title": regen_title,
                "platform": platform,
            },
        )

        # Post discussion summary to Slack
        discussion_summary = regenerator.get_discussion_summary(1500)
        _post_regen_progress_to_slack(
            slack, regen_title, platform, final, discussion_summary,
        )

        if final["decision"] == "reject":
            logger.info(
                "再生成後も不合格: %s — %s", regen_title[:30], final["summary"],
            )
            _save_rejected_articles(
                [{
                    "title": regen_title,
                    "platform": platform,
                    "content": content,
                    "rejection_reasons": final.get("summary", "再生成後も不合格"),
                    "rejection_stage": "regeneration_score",
                }],
                sheets,
            )
            try:
                sheets.update_status(article_id, "❌却下")
            except Exception:
                pass
        else:
            # Save regenerated content to store
            store.save(slug, {
                "title": regen_title,
                "content": content,
                "platform": platform,
                "source": stored.get("source", {}),
                "cover_image": stored.get("cover_image", ""),
                "scores": final,
                "regenerated": True,
                "agent_discussion": regen_result.get("agent_discussion", []),
            })

            # Update Sheets row with new scores
            sheets_data = final.get("for_sheets", {})
            if sheets_data:
                sheets_data["status"] = "⏳承認待ち"
                sheets_data["article_id"] = slug
                sheets_data["title"] = regen_title
            try:
                sheets.update_status(article_id, "⏳承認待ち")
            except Exception as e:
                logger.warning("Sheets status update failed: %s", e)

            logger.info(
                "再生成完了: %s (総合: %s)", regen_title[:30], final["overall_grade"],
            )

            # Notify via Gmail
            gmail_articles = [{
                "title": regen_title,
                "overall_grade": final.get("overall_grade", "-"),
                "evidence_level": final.get("evidence_level", "-"),
                "tier12_ratio": 0,
            }]
            sheets_url = os.getenv("GOOGLE_SHEET_URL", "")
            gmail.notify_pending_approval(gmail_articles, sheets_url)


def _post_regen_progress_to_slack(
    slack: SlackNotifier,
    title: str,
    platform: str,
    scores: dict,
    discussion_summary: str,
) -> None:
    """Post regeneration progress and discussion summary to Slack."""
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = os.getenv("SLACK_CHANNEL_ID", "C0AR7E9AFJ9")
    if not bot_token:
        return

    try:
        from slack_sdk import WebClient
        client = WebClient(token=bot_token)
    except ImportError:
        return

    grade = scores.get("overall_grade", "?")
    decision = scores.get("decision", "?")
    emoji = "✅" if decision == "approve" else "❌"

    message = (
        f"{emoji} *再生成完了*: {title[:60]}\n"
        f"*プラットフォーム*: {platform}\n"
        f"*総合グレード*: {grade}\n"
        f"*判定*: {decision}\n"
        f"*サマリー*: {scores.get('summary', '')}\n\n"
        f"--- エージェント議論 ---\n"
        f"{discussion_summary[:1500]}"
    )

    try:
        client.chat_postMessage(
            channel=channel_id,
            text=message[:3000],
        )
    except Exception as e:
        logger.error("Slack regeneration notification failed: %s", e)


# =====================================================================
# メインパイプライン
# =====================================================================

def run_pipeline(config: dict, prompts: dict, mode: str = "generate"):
    """メインパイプラインを実行する。

    Args:
        config: 設定dict。
        prompts: プロンプトテンプレートdict。
        mode: "generate"（生成+登録）or "publish"（承認済み投稿）。
    """
    logger.info("=" * 50)
    logger.info("AI記事自動生成システム 実行開始 (mode=%s)", mode)
    logger.info("日時: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 50)

    token_manager = TokenManager()
    slack = SlackNotifier()
    gmail = GmailNotifier()
    sheets = SheetsManager()
    feedback = FeedbackRecorder()

    if mode == "generate":
        # 収集 → 生成 → スコアリング → Sheets登録 → Gmail通知
        collected = collect_articles(config)
        total = sum(len(v) for v in collected.values())
        logger.info("収集完了: 合計%d件", total)

        if total == 0:
            logger.warning("収集記事0件。パイプライン終了。")
            return

        ranked = rank_articles(collected)
        approved, rejected = generate_and_score(ranked, config, prompts, token_manager)
        logger.info("スコアリング合格: %d件, 不合格: %d件", len(approved), len(rejected))

        register_for_approval(approved, sheets, gmail)
        _save_rejected_articles(rejected, sheets)

        # 再生成リクエストの処理
        regen_requests = sheets.get_regeneration_requests()
        if regen_requests:
            logger.info("再生成リクエスト: %d件", len(regen_requests))
            _process_regeneration_requests(
                regen_requests, sheets, slack, gmail, config, token_manager,
            )

        # 日次サマリー
        zenn_count = sum(1 for a in approved if a.get("platform") == "zenn")
        note_count = sum(1 for a in approved if a.get("platform") == "note")
        avg_score = 0.0
        if approved:
            scores = [a.get("scores", {}).get("objective_detail", {}).get(
                "citation_count", {}).get("count", 0) for a in approved]
            avg_score = sum(scores) / len(scores) if scores else 0.0
        stats = {
            "articles_generated": len(approved) + len(rejected),
            "articles_published": len(approved),
            "platforms": {"Zenn": zenn_count, "note": note_count},
            "avg_quality_score": avg_score,
            "errors": len(rejected),
        }
        slack.notify_daily_summary(stats)
        gmail.notify_daily_summary(stats)

    elif mode == "regenerate":
        # 再生成リクエストのみ処理
        regen_requests = sheets.get_regeneration_requests()
        if regen_requests:
            logger.info("再生成リクエスト: %d件", len(regen_requests))
            _process_regeneration_requests(
                regen_requests, sheets, slack, gmail, config, token_manager,
            )
        else:
            logger.info("再生成リクエストなし。")

    elif mode == "publish":
        # Sheetsから承認済み記事を取得して投稿
        results = publish_approved(sheets, config, slack, gmail, feedback)
        pub_total = sum(len(v) for v in results.values())
        logger.info("投稿完了: %d件", pub_total)

    # クリーンアップ（ゴミ溜まり防止）
    try:
        from utils.cleanup import cleanup_all
        cleanup_all()
    except Exception as e:
        logger.warning("Cleanup failed: %s", e)

    logger.info("=" * 50)
    logger.info("パイプライン完了 (mode=%s)", mode)
    logger.info("=" * 50)


# =====================================================================
# CLI
# =====================================================================

def main():
    """エントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="AI記事自動生成・投稿システム"
    )
    parser.add_argument(
        "--config", default="config/settings.yaml",
        help="設定ファイルパス",
    )
    parser.add_argument(
        "--collect-only", action="store_true",
        help="収集のみ実行（生成・投稿しない）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="生成+スコアリングまで実行（Sheets登録・投稿しない）",
    )
    parser.add_argument(
        "--generate", action="store_true",
        help="生成→スコアリング→Sheets登録→Gmail通知（デフォルト）",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Sheetsで承認済みの記事を投稿",
    )
    parser.add_argument(
        "--regenerate", action="store_true",
        help="🔄再生成リクエストのみ処理（収集・新規生成はスキップ）",
    )
    parser.add_argument(
        "--setup-sheets", action="store_true",
        help="Sheetsのフォーマット設定（ドロップダウン、条件付き書式等）",
    )
    parser.add_argument(
        "--learn", action="store_true",
        help="note人気記事をスクレイピングしてパターン学習",
    )
    args = parser.parse_args()

    if args.learn:
        from scrapers.note_scraper import NoteScraper
        from analyzers.pattern_extractor import PatternExtractor
        from learners.prompt_updater import PromptUpdater

        logger.info("=== Note学習モード開始 ===")
        scraper = NoteScraper()
        all_articles = []
        for category in ["business", "tech", "ai", "money", "lifestyle"]:
            logger.info("収集中: %s", category)
            articles = scraper.fetch_popular_articles(category, limit=30)
            logger.info("  → %d件取得", len(articles))
            all_articles.extend(articles)

        extractor = PatternExtractor()
        patterns = extractor.extract_winning_patterns(all_articles)

        updater = PromptUpdater()
        kb_path = updater.update_knowledge_base(patterns)
        sg_path = updater.suggest_prompt_improvements(patterns)
        logger.info("ナレッジ更新: %s", kb_path)
        logger.info("プロンプト改善案: %s", sg_path)
        logger.info("=== 学習完了: %d件のサンプルから学習 ===", len(all_articles))
        return

    config = load_config(args.config)
    prompts = load_prompts()

    # --- collect-only ---
    if args.collect_only:
        collected = collect_articles(config)
        ranked = rank_articles(collected)
        for platform, articles in ranked.items():
            print(f"\n=== {platform} ===")
            for i, a in enumerate(articles[:5], 1):
                print(
                    f"{i}. [{a.get('trend_score', 0):.1f}] {a['title']}"
                )
        return

    # --- dry-run ---
    if args.dry_run:
        logger.info("ドライラン: Sheets登録・投稿はスキップ")
        collected = collect_articles(config)
        ranked = rank_articles(collected)
        token_manager = TokenManager()
        approved, rejected = generate_and_score(
            ranked, config, prompts, token_manager
        )
        print(f"\n=== スコアリング合格: {len(approved)}件, 不合格: {len(rejected)}件 ===")
        for a in approved:
            scores = a["scores"]
            print(
                f"  [{scores.get('overall_grade', '?')}] "
                f"{a['title']} "
                f"(証拠Lv: {scores.get('evidence_level', '?')})"
            )
        return

    # --- setup-sheets ---
    if args.setup_sheets:
        sheets = SheetsManager()
        sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
        if sheet_id:
            sheets.setup_formatting(sheet_id)
            print("Sheetsフォーマット設定完了。")
        else:
            print("GOOGLE_SHEET_ID が未設定です。")
        return

    # --- regenerate ---
    if args.regenerate:
        run_pipeline(config, prompts, mode="regenerate")
        return

    # --- publish ---
    if args.publish:
        run_pipeline(config, prompts, mode="publish")
        return

    # --- generate (default) ---
    run_pipeline(config, prompts, mode="generate")


if __name__ == "__main__":
    main()
