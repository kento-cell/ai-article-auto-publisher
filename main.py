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
import hashlib
import io
import json
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
from collectors.google_trends_collector import GoogleTrendsCollector
from collectors.reddit_collector import RedditCollector
from collectors.rss_collector import RssCollector
from collectors.trend_detector import TrendDetector
from generators.claude_automator import ClaudeAutomator
from generators.local_llm import LocalLLM
from generators.regenerator import Regenerator
# DiagramGenerator was removed: Zenn renders ```mermaid natively and
# NotePublisher converts mermaid → ASCII at publish time, so the
# mmdc-backed generate-time conversion was pure overhead.
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


_TIER_BY_SOURCE_TYPE = {
    "arxiv": 1, "rss_jp": 2, "rss_kr": 2,
    "reddit": 3, "google_trends": 2, "bluesky": 3, "hacker_news": 2,
}


def _normalize_sources_for_scoring(article: dict) -> list[dict]:
    """Normalise the article's source metadata into the list-of-dicts
    shape the ObjectiveScorer expects.

    Two shapes flow in:
      * collector output: ``article["source"] = "arxiv"`` (string) plus
        a top-level ``url``/``title``.
      * regenerated articles: ``article["source"] = {"sources": [...]}``
        (wrapper dict produced by ``ArticleStore``).

    Both get flattened here so regeneration and initial generation
    exercise the same scorer logic — previously the regen path dropped
    the top-level URL/source_type and landed on an empty source list,
    which silently changed the grading baseline.
    """
    raw = article.get("source")
    if raw is None:
        raw = article.get("sources")

    sources: list[dict] = []
    if isinstance(raw, list):
        sources = [s for s in raw if isinstance(s, dict)]
    elif isinstance(raw, dict):
        nested = raw.get("sources")
        if isinstance(nested, list):
            sources = [s for s in nested if isinstance(s, dict)]
        else:
            sources = [raw]
    elif isinstance(raw, str) and raw:
        sources = [{
            "source": raw,
            "url": article.get("url", ""),
            "title": article.get("title", ""),
        }]

    # Infer tier when the collector didn't set one. Only arXiv preprints
    # qualify as tier 1 primary sources.
    for s in sources:
        if s.get("tier"):
            continue
        stype = str(s.get("source") or "").lower()
        if stype in _TIER_BY_SOURCE_TYPE:
            s["tier"] = _TIER_BY_SOURCE_TYPE[stype]
            continue
        url = str(s.get("url") or "").lower()
        if "arxiv.org" in url:
            s["tier"] = 1
        elif "reddit.com" in url or "trends.google" in url:
            s["tier"] = 3
        else:
            s["tier"] = 2

    return sources


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


_LEARNED_BLOCK_CACHE: dict[str, str] = {}


_LEARN_MERGE_WINDOW_DAYS = 7


def _compute_learn_adoption(content: str) -> dict:
    """Measure how strongly the generated article adopted the learn
    block hints.

    Three axes, all computed against the currently-merged learned
    block (loaded through the normal cache):

      * ``bracket_present``: does the title include the 【...】 bracket
        form that dominates the learn TOP10? One of the simplest
        success predictors for note.
      * ``phrase_hits``: count of "徹底/完全/保存版/解説" style phrase
        markers that showed up in the recent phrase ranking.
      * ``tag_coverage_pct``: share of the generator's output
        (approximated from the article's hashtag section) overlapping
        with the learned top-tag set.

    Returned values are informational — the caller stores them on the
    score dict but does not gate accept/reject on them. Used to watch
    whether learn injection is actually changing the LLM's output.
    """
    import re as _re

    first_line = content.splitlines()[0] if content else ""
    bracket_present = bool(_re.search(r"【[^】]+】", first_line))

    canonical_phrases = [
        "徹底", "完全", "保存版", "解説", "まとめ", "選",
        "狂気", "永久", "決定版", "朝メモ", "そもそも",
        "コアメンバー", "殿堂入り",
    ]
    phrase_hits = sum(1 for p in canonical_phrases if p in first_line)

    # Pull the tags line if present (our generator emits a hashtag
    # section footer); otherwise fall back to 0% coverage.
    tag_coverage_pct = 0.0
    learned_tag_set: set[str] = set()
    try:
        block = _load_learned_block()
        for line in block.splitlines():
            m = _re.match(r"^\s*-\s*#?([^\s:：]+)\s*[:：]\s*\d+", line)
            if m:
                learned_tag_set.add(m.group(1).lstrip("#"))
    except Exception:  # noqa: BLE001
        pass
    hashtag_matches = _re.findall(r"#(\w[\w_]{0,30})", content)
    if learned_tag_set and hashtag_matches:
        overlap = sum(1 for t in hashtag_matches if t in learned_tag_set)
        tag_coverage_pct = 100.0 * overlap / len(hashtag_matches)

    return {
        "bracket_present": bracket_present,
        "phrase_hits": phrase_hits,
        "phrase_total": len(canonical_phrases),
        "tag_coverage_pct": round(tag_coverage_pct, 1),
    }


def _parse_learn_sections(text: str) -> dict[str, list[str]]:
    """Extract the bullet/numbered items from named sections of a
    single learn-report markdown.

    Returns a dict with keys ``top_titles``, ``phrases``, ``tags``.
    """
    def _section(marker: str, limit: int) -> list[str]:
        lines = text.splitlines()
        out: list[str] = []
        in_sec = False
        for line in lines:
            if line.startswith("## "):
                if marker in line:
                    in_sec = True
                    continue
                if in_sec:
                    break
            if in_sec and line.strip().startswith(
                ("-", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.",
                 "9.", "10.")
            ):
                out.append(line.strip())
                if len(out) >= limit:
                    break
        return out

    return {
        "top_titles": _section("トップ記事", 10),
        "phrases": _section("よく使われるパターン", 8),
        "tags": _section("タグ分布", 20),
    }


def _load_failure_patterns(max_chars: int = 900) -> str:
    """Read ``docs/knowledge/quality_recurring_failures.md`` and return a
    short prompt-injectable block summarising the failure patterns the
    pipeline keeps hitting. Silent when the file is missing.

    The LLM sees this as "known traps — avoid these at write time" so
    the self-improvement log actually feeds back into generation, not
    just sits on disk for humans.
    """
    path = Path("docs/knowledge/quality_recurring_failures.md")
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("failure pattern read failed: %s", exc)
        return ""

    # Extract just the "観測:" and "対処候補:" lines of each numbered
    # section so the prompt stays tight. Skip the stale marker rows.
    patterns: list[str] = []
    current_title = ""
    for line in text.splitlines():
        if line.startswith("## "):
            current_title = line.lstrip("# ").strip()
            continue
        stripped = line.strip()
        if stripped.startswith("**観測:**"):
            obs = stripped.replace("**観測:**", "").strip()
            if current_title and obs:
                patterns.append(f"- {current_title}: {obs}")
        if len(patterns) >= 6:
            break

    if not patterns:
        return ""

    block = (
        "\n\n【過去の不合格・偏りパターン — 今回は避けること】\n"
        + "\n".join(patterns)
        + "\n上記のパターンに該当する構成・表現は出力しない。"
    )
    if len(block) > max_chars:
        block = block[:max_chars] + "…\n"
    return block


def _load_learned_block() -> str:
    """Read the last *_LEARN_MERGE_WINDOW_DAYS* learn reports and build a
    prompt-injectable block.

    Why a rolling window instead of just the newest file:
      - A single day's scrape is noisy (20 articles × 5 categories ≈
        1 data point per tag, large variance).
      - A 7-day merge smooths single-day spikes and surfaces tags that
        are *consistently* popular.
      - Newest titles still stay on top (sorted by file date desc) so
        the LLM sees fresh bait along with the averaged tag pool.

    We also append the quality-failure patterns from
    ``docs/knowledge/quality_recurring_failures.md`` so the LLM learns
    from past mistakes, not just past successes.

    Cached per-process.
    """
    if "note" in _LEARNED_BLOCK_CACHE:
        return _LEARNED_BLOCK_CACHE["note"]

    block = ""
    try:
        knowledge_dir = Path("docs/knowledge/note-trends")
        if not knowledge_dir.exists():
            _LEARNED_BLOCK_CACHE["note"] = ""
            return ""
        reports = sorted(
            knowledge_dir.glob("*_auto_learning.md"),
            reverse=True,
        )
        if not reports:
            _LEARNED_BLOCK_CACHE["note"] = ""
            return ""

        window = reports[:_LEARN_MERGE_WINDOW_DAYS]
        latest = window[0]

        # Aggregate titles (dedup, keep newest order) + phrases + tags
        # (sum counts across files to stabilise the ranking).
        merged_titles: list[str] = []
        seen_titles: set[str] = set()
        merged_phrases: dict[str, int] = {}
        merged_tag_counts: dict[str, int] = {}
        import re as _re
        tag_line_re = _re.compile(r"^-\s*#?([^\s:：]+)\s*[:：]\s*(\d+)")
        phrase_line_re = _re.compile(r"^-\s*([^:：]+?)\s*[:：]\s*(\d+)")

        for rep in window:
            try:
                sections = _parse_learn_sections(
                    rep.read_text(encoding="utf-8")
                )
            except OSError:
                continue
            for t in sections["top_titles"]:
                key = t.split("]")[0] if "[" in t else t
                if key not in seen_titles:
                    seen_titles.add(key)
                    merged_titles.append(t)
                if len(merged_titles) >= 10:
                    break
            for p in sections["phrases"]:
                m = phrase_line_re.match(p)
                if m:
                    name = m.group(1).strip()
                    merged_phrases[name] = (
                        merged_phrases.get(name, 0) + int(m.group(2))
                    )
            for tg in sections["tags"]:
                m = tag_line_re.match(tg)
                if m:
                    name = m.group(1).strip()
                    merged_tag_counts[name] = (
                        merged_tag_counts.get(name, 0) + int(m.group(2))
                    )

        if not (merged_titles or merged_phrases or merged_tag_counts):
            _LEARNED_BLOCK_CACHE["note"] = ""
            return ""

        phrases_ranked = sorted(
            merged_phrases.items(), key=lambda kv: -kv[1]
        )[:5]
        tags_ranked = sorted(
            merged_tag_counts.items(), key=lambda kv: -kv[1]
        )[:10]

        parts = [
            "\n\n【直近の人気note記事から学習したパターン — 真似すべき成功例】",
            f"※ 直近{len(window)}日分の学習レポートを統合 "
            f"(最新: {latest.stem})",
        ]
        if merged_titles:
            parts.append("\n★ 最近バズったタイトル(♥いいね数付き、参考にせよ):")
            parts.extend(merged_titles[:10])
        if phrases_ranked:
            parts.append("\n★ 頻出するタイトル型(集計):")
            for name, cnt in phrases_ranked:
                parts.append(f"- {name}: {cnt}")
        if tags_ranked:
            parts.append("\n★ 反応の良いタグ(集計):")
            for name, cnt in tags_ranked:
                parts.append(f"- #{name}: {cnt}")
        parts.append(
            "\n上記のタイトル/フレーズ/タグの「型」を踏襲しつつ、"
            "記事内容に沿った独自のバリエーションで書くこと。"
            "単純コピーは避け、構造だけ真似る。"
        )
        block = "\n".join(parts) + "\n"

        # Append the failure-pattern block so the LLM avoids known traps.
        block += _load_failure_patterns()
    except Exception as exc:
        logger.warning("learned block load failed: %s", exc)
        block = ""

    _LEARNED_BLOCK_CACHE["note"] = block
    return block


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


_RECENT_AREA_WINDOW = 6
_RECENT_AREA_PATH = Path("data/recent_note_areas.json")


def _load_recent_note_areas() -> list[str]:
    """Return the rolling window of recently-used note areas."""
    if not _RECENT_AREA_PATH.exists():
        return []
    try:
        data = json.loads(_RECENT_AREA_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(a) for a in data][-_RECENT_AREA_WINDOW:]
    except Exception:
        pass
    return []


def _remember_note_area(area: str) -> None:
    """Append *area* to the recent-used list, capped at the window size."""
    if not area:
        return
    areas = _load_recent_note_areas()
    areas.append(area)
    areas = areas[-_RECENT_AREA_WINDOW:]
    try:
        _RECENT_AREA_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_AREA_PATH.write_text(
            json.dumps(areas, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        logger.debug("recent areas save failed: %s", exc)


def _area_of_article(article: dict) -> str:
    """Return the normalised area token associated with *article*.

    Prefers a ``query`` field (first token is the area), falls back to
    :func:`_extract_area_hint` scanning.
    """
    q = article.get("query") or ""
    if q:
        tokens = q.split()
        if tokens:
            return tokens[0]
    return _extract_area_hint(article)


def _extract_area_hint(article: dict) -> str:
    """Extract a locality keyword (e.g. "下北沢") from the source article.

    Order of precedence:
      1. ``article["query"]`` — first token is the already-normalised
         area name (most trustworthy).
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
    ("焼肉", "yakiniku grill"), ("カレー", "curry spice"),
    ("韓国", "korea seoul"), ("美容", "beauty cosmetics"),
    ("コスメ", "cosmetics"), ("ファッション", "fashion"),
    ("旅行", "travel"), ("観光", "travel landmark"),
    ("AI", "artificial intelligence"), ("LLM", "ai technology"),
    ("Claude", "ai technology"), ("ChatGPT", "ai technology"),
    ("Python", "python code"), ("React", "web development"),
    ("論文", "research paper"), ("機械学習", "machine learning"),
    ("投資", "finance investment"), ("株価", "stock market finance"),
    ("副業", "business laptop"),
    ("マネタイズ", "business money"), ("起業", "startup"),
    ("鉄道", "train railway"), ("地下鉄", "subway tokyo"),
    ("電車", "train railway"), ("駅", "train station japan"),
    ("俳優", "actor celebrity"), ("女優", "actress celebrity"),
    ("歌手", "singer concert"), ("アーティスト", "music concert"),
    ("政治", "politics government"), ("首相", "politics government"),
    ("大統領", "politics government"), ("中国", "china beijing"),
    ("NBA", "basketball nba"), ("バスケ", "basketball"),
    ("サッカー", "soccer football"), ("野球", "baseball japan"),
    ("テーマパーク", "theme park ride"), ("ディズニー", "theme park castle"),
    ("音楽", "music concert stage"), ("ライブ", "live concert"),
]


# Tokens that appear in almost every trend article body but make
# terrible image subjects on their own. Excluded from the body-scan
# proper-noun heuristic so "Bluesky Twitter SNS" stops winning.
_IMAGE_QUERY_BLACKLIST: frozenset[str] = frozenset({
    "bluesky", "twitter", "facebook", "instagram", "tiktok", "reddit",
    "youtube", "linkedin", "threads", "mastodon", "snapchat",
    "google", "maps", "map", "apple", "amazon", "microsoft",
    "note", "zenn", "qiita", "sns", "web", "app", "api",
    "kento", "username", "userprofile",
    "http", "https", "www", "com", "org", "net",
    "the", "and", "for", "with", "this", "that", "from", "you",
    "your", "are", "was", "has", "have", "can", "will",
    # Common tail fragments that arise when word-boundary anchors
    # fail on mixed JP/ASCII text (e.g. "B|luesky|" → "luesky").
    "luesky", "eddit", "oogle", "witter", "acebook", "nstagram",
    "iktok", "outube", "inkedin", "hreads", "astodon",
})


def _extract_image_query(title: str, content: str = "") -> str:
    """Extract a short English-friendly search query from a JP title+body.

    Strategy:
      1. Match known Japanese theme keywords in title → English terms.
      2. Extract ASCII alphanumeric tokens from title (product names).
      3. If still empty, scan body for ASCII tokens + theme keywords —
         pure-JP trending topics (e.g. "森英恵") have no title ASCII but
         the generated body usually contains proper nouns like "Ulala",
         "Bluesky", "NBA" that make much better image queries.
      4. Last resort: domain-guessed fallback.

    Unsplash/Pexels handle English far better than Japanese and outright
    reject very long queries, so we cap at ~3 short tokens.
    """
    if not title and not content:
        return "technology"

    # Scrub markdown image syntax + Unsplash URL hashes before scanning:
    # regenerated articles already carry ![alt](data/images/xxx "https://
    # images.unsplash.com/photo-…?ixid=M3w5MTgxMTd8MHw…") blocks, and the
    # raw token scan would otherwise harvest `M3w5MTgxMTd8MHw` as a
    # "proper noun" and pollute the image query.
    if content:
        content = re.sub(
            r"!\[[^\]]*\]\([^)]*\)", " ", content
        )
        content = re.sub(r"https?://\S+", " ", content)

    keywords: list[str] = []

    # 1. Theme keyword mapping (title) — most reliable signal.
    combined_for_theme = f"{title}\n{content[:500]}"
    for jp, en in _THEME_KEYWORDS:
        if jp.lower() in combined_for_theme.lower() and en not in keywords:
            keywords.append(en)
            if len(keywords) >= 2:
                break

    # 2. Pull out ASCII tokens from title first (more specific).
    # \b anchors guard against picking up "luesky" as a substring of
    # Bluesky when scanning lowercase after a blacklisted uppercase hit.
    for m in re.findall(r"\b[A-Za-z][A-Za-z0-9+]{2,14}\b", title):
        if m.lower() in _IMAGE_QUERY_BLACKLIST:
            continue
        if m not in keywords:
            keywords.append(m)
        if len(keywords) >= 3:
            break

    # 3. If title did not yield ASCII tokens (pure JP title), scan the
    # first ~1500 chars of content — LLM body usually cites English
    # proper nouns (brand names, platforms, artists). Prefer tokens
    # that appear multiple times so we surface the actual subject
    # rather than incidental mentions.
    if len(keywords) < 2 and content:
        head = content[:2000]
        from collections import Counter as _Counter
        # Capitalised tokens first (proper nouns like "Ulala", "NBA").
        caps = [
            m for m in re.findall(r"\b[A-Z][A-Za-z0-9+]{2,14}\b", head)
            if m.lower() not in _IMAGE_QUERY_BLACKLIST
        ]
        counts = _Counter(caps)
        # Sort by frequency desc, then by order of first occurrence.
        first_idx: dict[str, int] = {}
        for idx, t in enumerate(caps):
            first_idx.setdefault(t, idx)
        for tok, _cnt in sorted(
            counts.items(), key=lambda kv: (-kv[1], first_idx[kv[0]])
        ):
            if tok not in keywords:
                keywords.append(tok)
            if len(keywords) >= 3:
                break
        # If still short, try lowercase tokens the same way.
        if len(keywords) < 2:
            lows = [
                m for m in re.findall(r"\b[a-z][a-z0-9+]{3,14}\b", head)
                if m not in _IMAGE_QUERY_BLACKLIST
            ]
            lc_counts = _Counter(lows)
            lc_first: dict[str, int] = {}
            for idx, t in enumerate(lows):
                lc_first.setdefault(t, idx)
            for tok, _cnt in sorted(
                lc_counts.items(), key=lambda kv: (-kv[1], lc_first[kv[0]])
            ):
                if tok not in keywords:
                    keywords.append(tok)
                if len(keywords) >= 3:
                    break

    if keywords:
        return " ".join(keywords[:3])

    # 4. Last resort: domain-guessed fallback from title+content.
    hay = combined_for_theme
    if any(w in hay for w in ("AI", "ＡＩ", "LLM", "モデル", "論文")):
        return "technology ai"
    if any(w in hay for w in ("店", "グルメ", "食", "メニュー", "ラーメン")):
        return "food restaurant"
    if any(w in hay for w in ("韓国", "K-POP", "アイドル")):
        return "korea seoul city"
    if any(w in hay for w in ("音楽", "歌", "シンガー", "ライブ")):
        return "music concert stage"
    if any(w in hay for w in ("スポーツ", "試合", "選手")):
        return "sports stadium"
    return "lifestyle"


_IMAGE_HOST_ALLOWLIST = {
    "images.unsplash.com", "plus.unsplash.com",
    "images.pexels.com", "www.pexels.com",
    "upload.wikimedia.org",
}
_IMAGE_MIME_ALLOWLIST = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB is plenty for cover art


def _download_image(url: str, dest: Path) -> Path | None:
    """Download an image from a URL to a local destination.

    Returns the destination path on success, ``None`` on failure.
    """
    if not url:
        return None
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _IMAGE_HOST_ALLOWLIST:
        logger.warning(
            "Image download rejected — host %s not in allowlist", parsed.hostname,
        )
        return None
    try:
        import requests as _requests
        # allow_redirects=False pins the resolved host/scheme check to
        # the exact URL we validated above. An Unsplash mirror that
        # happened to 302 to an internal address would otherwise
        # bypass the allowlist entirely. Use a context manager so an
        # early-return on content-type/size failure still closes the
        # connection instead of leaking the TCP socket.
        with _requests.get(
            url, timeout=30, stream=True, allow_redirects=False,
        ) as resp:
            if 300 <= resp.status_code < 400:
                logger.warning(
                    "Image download rejected — refusing redirect to %s",
                    resp.headers.get("Location", "<unknown>"),
                )
                return None
            resp.raise_for_status()
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and ctype not in _IMAGE_MIME_ALLOWLIST:
                logger.warning("Image download rejected — bad content-type %s", ctype)
                return None
            # Stream with a hard byte cap so a malicious response can't
            # fill the disk or RAM.
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _IMAGE_MAX_BYTES:
                    logger.warning("Image download rejected — exceeds %d bytes", _IMAGE_MAX_BYTES)
                    return None
                chunks.append(chunk)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"".join(chunks))
        return dest
    except Exception as exc:
        logger.warning("Image download failed (%s): %s", url, exc)
        return None


def _fetch_cached_images(
    sourcer, query: str, count: int, cache_salt: str = ""
) -> list[dict]:
    """Fetch images from ImageSourcer with per-process caching.

    cache_salt (usually a slug) is included in the cache key so two
    articles that happen to resolve to the same query (e.g. both fall
    through to "lifestyle") don't end up with literally the same photos.
    """
    cache_key = f"{cache_salt}::{query}::{count}"
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
    """Build a Markdown image block with both local path and remote URL.

    The remote CDN URL (e.g. ``https://images.unsplash.com/photo-xxx``)
    is embedded as the markdown title attribute so platforms that can
    embed external images (note.com via HTML clipboard paste) can swap
    the local path for the live URL at publish time. Zenn keeps using
    the git-tracked local path because its publishing model is a git
    repo of images.
    """
    rel = local_path.as_posix()
    if "data/images/" not in rel:
        rel = f"data/images/stock/{local_path.name}"
    safe_alt = alt.replace("[", "(").replace("]", ")")
    remote = (image.get("url") or image.get("download_url") or "").strip()
    if remote:
        return f'![{safe_alt}]({rel} "{remote}")\n'
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

    query = _extract_image_query(title, content)
    total_needed = 1 + section_count
    images = _fetch_cached_images(
        sourcer, query, total_needed, cache_salt=slug
    )

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

    # Google Trends: trending topics in Japan for note
    try:
        gt_cfg = config.get("collection", {}).get("google_trends", {}) or {}
        gt = GoogleTrendsCollector(
            max_results=gt_cfg.get("max_results", 30),
        )
        articles = gt.collect()
        collected["note"].extend(articles)
        logger.info("Google Trends: %d件収集", len(articles))
    except Exception as e:
        logger.error("Google Trends収集エラー: %s", e)

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


def _build_regen_feedback(obj_result: dict, subj_result: dict, final: dict) -> str:
    """Build a Japanese feedback block to inject into a regen prompt.

    Names the weakest metrics so the LLM knows what to improve on.
    Used by the borderline-B auto-regen loop (OptiBlogAi pattern).
    """
    weak: list[str] = []
    metric_labels = {
        "citation_count": "引用数を増やす(最低5件、URL+取得日付き)",
        "citation_format": "引用ブロックに必ずURLと取得日を併記",
        "visual_count": "画像/表/コードブロック/Mermaid図を最低5個含める",
        "evidence_level": "tier1〜2の一次ソースを増やす",
    }
    metrics = obj_result.get("metrics") or {}

    # Word count is high-leverage — make the feedback concrete by
    # including the *actual* current count so the LLM can reason about
    # how much to add. Gemma3 previously ignored "2500〜3500字" because
    # it had no measuring reference.
    wc = metrics.get("word_count") or {}
    current_chars = wc.get("count", 0)
    if wc.get("grade") in ("B", "C") or current_chars < 2400:
        shortfall = max(2800 - current_chars, 500)
        weak.append(
            f"- 文字数が{current_chars}字しかない。**最低2800字、目標3200字**まで伸ばす"
            f"(現在より{shortfall}字以上追加)。以下のいずれかで各H2セクションを厚くする:\n"
            f"    ・各セクションに固有名詞つきの具体例を2つ以上\n"
            f"    ・引用ブロック(>)で一次情報を直接引く(最低3箇所)\n"
            f"    ・数値データ(再生回数/売上/割合)を本文に埋め込む\n"
            f"    ・読者への問いかけ→回答の往復で1段落追加"
        )

    for name, data in metrics.items():
        if name == "word_count":
            continue
        if isinstance(data, dict) and data.get("grade") == "B":
            label = metric_labels.get(name)
            if label:
                weak.append(f"- {label}")

    sub_dims = {
        "originality": "独自視点を強化(他記事との差別化、未報道の角度)",
        "accuracy": "数値・固有名詞を本文中で根拠リンクと共に再掲",
        "readability": "見出しを明確化、段落を短く、要点を冒頭に",
        "engagement": "冒頭フックと具体例(数字・人物・固有名詞)を増やす",
    }
    for dim, label in sub_dims.items():
        d = subj_result.get(dim) or {}
        if d.get("grade") in ("B", "C"):
            weak.append(f"- {label}")

    if not weak:
        weak.append("- 細部の磨き込み(具体例・数字・固有名詞を1.5倍に)")

    return (
        "\n\n【⚠ 自動再生成モード】\n"
        f"前回の試行は総合B(numeric={final.get('numeric_score', 0):.1f})でした。\n"
        "以下を改善した完全版を出力してください:\n"
        + "\n".join(weak[:6])
        + "\n再生成では同じ構成・同じトピックを保ちつつ、上記の弱点を解消すること。\n"
    )


# Borderline B band that triggers one auto-regen attempt. Above the
# ceiling we already have a good article; below the floor it's too
# weak for regen to rescue cheaply.
_REGEN_FLOOR = 75.0
_REGEN_CEILING = 87.5
_REGEN_MAX_ATTEMPTS = 1


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
    _regen_attempt: int = 0,
    _regen_feedback: str = "",
    _skip_save: bool = False,
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
    #
    # For note, the research brief is load-bearing: without it the LLM
    # tends to hallucinate store names / prices. A second auto-regen
    # run (``_regen_feedback`` non-empty) is exempt because by then
    # Codex already failed once and retrying in-band would just burn
    # budget — the caller will re-score and decide.
    research_block = ""
    if platform == "note":
        research_block = _codex_research_brief(article)
        if not research_block and not _regen_feedback:
            logger.warning(
                "[note] Codex research brief is empty — rejecting article "
                "rather than generating ungrounded content. "
                "Rerun when the Codex CLI / network is available."
            )
            return {
                "rejected": True,
                "reason": "research brief empty (fail-closed)",
                "title": article.get("title", ""),
                "platform": platform,
                "source": article.get("source", ""),
            }

    # Inject learned patterns (popular titles / phrases / tags) into the
    # note prompt. Zenn is tech-focused and does not benefit from
    # note-trend mimicry. Silent no-op when no learn report exists.
    # Gated on experiments.yaml so A/B runs can compare w/ vs w/o.
    from utils.experiments import is_enabled as _xp_enabled
    learned_block = ""
    if platform == "note" and _xp_enabled("learn.learned_block"):
        learned_block = _load_learned_block()

    # --- 生成 ---
    try:
        prompt = (
            template.format(**article)
            + structure_instruction
            + bracket_hint
            + research_block
            + learned_block
            + _regen_feedback  # empty unless this is an auto-regen attempt
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
    # Short prefix for readability + 8-char hash of the full title to
    # prevent collisions when two articles share the first 20 chars
    # (previously caused duplicate publishes, see git history).
    _raw_title = article.get('title', 'untitled')
    _safe_title = re.sub(r'[\\/:*?"<>|]', '_', _raw_title[:20])
    _title_hash = hashlib.sha1(_raw_title.encode('utf-8')).hexdigest()[:8]
    slug = f"{platform}-{_safe_title}-{_title_hash}"

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

    # NOTE: raw ```mermaid blocks intentionally flow through untouched.
    # Zenn renders them natively; NotePublisher converts them to ASCII
    # flow at publish time. A prior generate-time PNG conversion launched
    # mmdc on every article and produced local paths that neither
    # platform could serve — see diagram_generator.py removal.

    # --- 客観スコア ---
    evidence_mgr = EvidenceManager()
    forbidden = config.get("evidence", {}).get("forbidden_phrases", [])
    sources = _normalize_sources_for_scoring(article)

    chain_blacklist = config.get("evidence", {}).get(
        "gourmet_rules", {}
    ).get("chain_blacklist", [])

    obj_scorer = ObjectiveScorer()
    obj_result = obj_scorer.score(content, {
        "sources": sources,
        "forbidden_phrases": forbidden,
        "chain_blacklist": chain_blacklist,
        "title": article.get("title", ""),
        "platform": platform,  # required for first_hand_experience zenn skip
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

    # --- 自動再生成ループ (OptiBlogAi pattern) ---
    # Borderline B articles get one retry with a feedback prompt that
    # names the weakest metrics. Compare numeric scores and keep the
    # winner. Stops after one attempt to bound compute + Places API
    # cost at ~2x for borderline articles.
    #
    # NOTE: regen only fires on the local-LLM path because Claude
    # generation goes through `claude.generate_article(template, article)`
    # which rebuilds its own prompt and would silently ignore our
    # feedback hint. Claude is currently disabled in `_init_llm` anyway,
    # so this guard is also future-proofing.
    # Regen trigger: borderline-B band (score 75-87.5) OR severely thin
    # content (<1900 chars). Thin articles slip past the score gate
    # because they still hit evidence/heading/visual thresholds, but the
    # reader perceives them as hollow — we want a second pass even if
    # the numeric score already says "approve".
    _wc_current = (obj_result.get("metrics", {})
                   .get("word_count", {}).get("count", 0))
    _thin_content = _wc_current > 0 and _wc_current < 1900
    if (
        use_local
        and _regen_attempt < _REGEN_MAX_ATTEMPTS
        and final.get("decision") == "approve"
        and final.get("overall_grade") in ("A", "B")
        and (
            (final.get("overall_grade") == "B"
             and _REGEN_FLOOR <= final.get("numeric_score", 0) < _REGEN_CEILING)
            or _thin_content
        )
    ):
        feedback = _build_regen_feedback(obj_result, subj_result, final)
        logger.info(
            "[%s] 自動再生成 試行%d (現スコア=%.1f): %s",
            platform,
            _regen_attempt + 1,
            final.get("numeric_score", 0),
            article["title"][:30],
        )
        retry = _generate_single_article(
            article=article,
            platform=platform,
            template=template,
            claude=claude,
            local_llm=local_llm,
            use_local=use_local,
            token_manager=token_manager,
            config=config,
            prompts=prompts,
            _regen_attempt=_regen_attempt + 1,
            _regen_feedback=feedback,
            _skip_save=True,  # outer call owns the save
        )
        if (
            retry
            and not retry.get("rejected")
            and retry.get("scores", {}).get("numeric_score", 0)
            > final.get("numeric_score", 0)
        ):
            logger.info(
                "[%s] 再生成で改善: %.1f → %.1f",
                platform,
                final.get("numeric_score", 0),
                retry["scores"].get("numeric_score", 0),
            )
            # Adopt the retry's content/scores wholesale.
            content = retry["content"]
            final = retry["scores"]
            obj_result = retry.get("_obj_result", obj_result)
            subj_result = retry.get("_subj_result", subj_result)
            # Structure can re-roll on retry (different bracket hint may
            # nudge LLM toward another template) — adopt it for diagnostics.
            if retry.get("structure_type"):
                structure_name = retry["structure_type"]
            # The slug stays the same since article identity is unchanged,
            # but the cover image was regenerated for the retry — adopt it.
            if retry.get("cover_image"):
                _retry_cover = retry["cover_image"]
            else:
                _retry_cover = None
        else:
            logger.info(
                "[%s] 再生成スキップ(改善なし): keep %.1f",
                platform,
                final.get("numeric_score", 0),
            )
            _retry_cover = None
    else:
        _retry_cover = None

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
    if _retry_cover:
        # Retry already produced one — reuse it instead of paying the
        # cover generator twice for the same article identity.
        cover_path = _retry_cover
    else:
        cover_gen = CoverGenerator()
        cover_path = cover_gen.generate(
            title=article["title"],
            platform=platform,
            slug=slug,
        )

    # Measure how much of the learn block this generation actually
    # adopted. This closes the loop — without measurement, the prompt
    # injection is a hope, not a feedback signal. Low adoption over
    # many runs is a prompt-design bug, not a model capacity issue.
    if platform == "note" and _xp_enabled("learn.track_adoption"):
        adoption = _compute_learn_adoption(content)
        final["learn_adoption"] = adoption
        logger.info(
            "[%s] learn採用率: brackets=%s phrases=%d/%d tags=%.0f%%",
            platform,
            "✓" if adoption["bracket_present"] else "✗",
            adoption["phrase_hits"], adoption["phrase_total"],
            adoption["tag_coverage_pct"],
        )

    logger.info(
        "[%s] 生成完了: %s (総合: %s, 証拠Lv: %s)",
        platform,
        article["title"][:30],
        final["overall_grade"],
        final["evidence_level"],
    )

    # Save article content for later --publish retrieval (the recursive
    # regen call passes _skip_save=True to let the outer call own this)
    if not _skip_save:
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
        # Stashed so the outer call (when this is a regen retry) can
        # pull through obj/subj details if it adopts this content.
        "_obj_result": obj_result,
        "_subj_result": subj_result,
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

        # note: Google Trendsのトレンド系ソースを1枠予約する。
        # Google Trends topics surface timely buzz that RSS feeds
        # may miss, so we guarantee one slot when available.
        # Diversity strategy: rank candidates by *least recently
        # used area first, then trend_score*.
        selection = candidates[:articles_per_week]
        if platform == "note":
            from collections import Counter
            recent_areas = _load_recent_note_areas()
            recent_counts = Counter(recent_areas)
            trends_candidates = [
                a for a in candidates if a.get("source") == "google_trends"
            ]

            def _area_rank(art: dict) -> tuple[int, float]:
                # Lower recent_count wins, ties broken by higher trend_score.
                area = _area_of_article(art)
                return (
                    -recent_counts.get(area, 0),
                    float(art.get("trend_score", 0)),
                )

            trends_candidates.sort(key=_area_rank, reverse=True)

            # Log topic distribution so we can see why a pick was made.
            _area_histo = Counter(
                _area_of_article(a) or "-" for a in trends_candidates[:20]
            )
            logger.info(
                "[note] Google Trends候補分布(top20): %s",
                ", ".join(f"{k}×{v}" for k, v in _area_histo.most_common(10)),
            )

            top_trends = trends_candidates[0] if trends_candidates else None
            if top_trends and top_trends not in selection:
                if selection:
                    selection[-1] = top_trends
                else:
                    selection = [top_trends]
                picked_area = _area_of_article(top_trends) or "-"
                logger.info(
                    "[note] Google Trends枠を確保: [%s] %s (recent: %s)",
                    picked_area,
                    top_trends.get("title", "")[:40],
                    ",".join(recent_areas) or "none",
                )
                _remember_note_area(picked_area)

        for article in selection:
            try:
                result = _generate_single_article(
                    article, platform, template,
                    claude, local_llm, use_local,
                    token_manager, config, prompts,
                )
                # Record source as used ONLY on successful approval.
                # Rejected articles stay eligible so a future run (with
                # fixes / different prompt rotation) can retry them
                # instead of burning through the candidate pool.
                if result is None:
                    pass
                elif result.get("rejected"):
                    rejected.append(result)
                else:
                    source_url = article.get("url", "")
                    if source_url:
                        _save_generated_source(source_url)
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

    seen_ids: set[str] = set()
    # Last-line-of-defence deny patterns. Even if a row made it through
    # bulk_approve, these patterns MUST never hit live — they caused
    # public retractions in 2026-04 (習近平/妻夫木聡/李在明/メッツ).
    # Match both the stored title and the Japanese-extracted title
    # since the extractor can reveal a banned phrase that was shortened
    # in the sheet title.
    import re as _re
    _PUBLISH_DENY_PATTERNS = [
        _re.compile(r"氏の\s*(?:Bluesky|Twitter|X|Instagram|Threads|TikTok)\s*投稿"),
        _re.compile(r"さんの\s*(?:Bluesky|Twitter|X|Instagram|Threads|TikTok)\s*投稿"),
        _re.compile(r"(?:Bluesky|Twitter|X|Instagram|Threads|TikTok)\s*投稿が話題"),
        _re.compile(r"(?:Bluesky|Twitter|X|Instagram|Threads|TikTok)\s*投稿を徹底"),
        _re.compile(r"(?:Bluesky|Twitter|X|Instagram|Threads|TikTok)\s*投稿から徹底"),
        _re.compile(r"(?:Bluesky|Twitter|X|Instagram|Threads|TikTok)\s*投稿から読み解"),
        _re.compile(r"架空の\s*URL"),
    ]

    def _deny_reason(txt: str) -> str | None:
        for pat in _PUBLISH_DENY_PATTERNS:
            m = pat.search(txt)
            if m:
                return m.group(0)
        return None

    for article_data in approved:
        platform = article_data.get("platform", "")
        title = article_data.get("title", "")
        article_id = article_data.get("article_id", "")

        # Guard against duplicate approved rows sharing an article_id.
        # Root-caused to slug collisions when two titles share the first
        # 20 chars (see slug construction below, now hash-suffixed).
        if article_id in seen_ids:
            logger.warning(
                "重複 article_id をスキップ: %s", article_id
            )
            continue
        seen_ids.add(article_id)

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

        # Final deny check — refuse to publish when the stored title,
        # the extracted JP title, or the first 2KB of body matches any
        # of the hallucination patterns. Flip the sheet row to ❌却下
        # so the operator sees why it was blocked and does not retry
        # it blindly.
        _deny_hit = (
            _deny_reason(article_data.get("title", ""))
            or _deny_reason(title)
            or _deny_reason(content[:2000])
        )
        if _deny_hit:
            logger.warning(
                "[%s] deny-pattern hit → publish 拒否: %s — matched %r",
                platform, title[:40], _deny_hit,
            )
            try:
                sheets.update_status(article_id, "❌却下")
            except Exception as _exc:
                logger.warning("sheet status update failed: %s", _exc)
            continue

        try:
            if platform == "zenn":
                scores = stored.get("scores", {})
                numeric_score = float(scores.get("numeric_score") or 0)
                # Threshold: 77.5 — tuned to Gemma3's realistic ceiling
                # on arXiv/AI topics. The old 82.5 required composite
                # grade ≈ A- which Gemma3 rarely hits on research papers.
                # Below 77.5 the article still feels undercooked and
                # falls back to Zenn Scraps.
                ZENN_ARTICLE_THRESHOLD = 77.5
                if numeric_score >= ZENN_ARTICLE_THRESHOLD:
                    logger.info(
                        "[zenn] score=%.1f >= %.1f → 記事投稿",
                        numeric_score, ZENN_ARTICLE_THRESHOLD,
                    )
                    url = _publish_zenn(article_id, title, content, stored)
                else:
                    logger.info(
                        "[zenn] score=%.1f < %.1f → スクラップ投稿",
                        numeric_score, ZENN_ARTICLE_THRESHOLD,
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


def _fetch_topic_cover(title: str) -> Path | None:
    """Download an Unsplash photo themed to *title* for the eyecatch.

    Falls through to ``None`` so the caller can decide whether to
    fall back to the PIL KENTO mascot (NoteCoverGenerator) or skip
    the cover entirely.
    """
    try:
        from generators.image_sourcer import ImageSourcer
        sourcer = ImageSourcer()
        query = _extract_image_query(title)
        results = sourcer.find_images(query, count=1)
        if not results:
            logger.info("[cover] no Unsplash result for %r", query)
            return None
        url = results[0].get("url") or results[0].get("download_url")
        if not url:
            return None
        safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", title)[:40]
        out = Path("data/images/covers") / f"unsplash_{safe_slug}.jpg"
        # Route through the shared allowlisted downloader so the cover
        # path is not weaker than the rest of the pipeline.
        if _download_image(url, out) is None:
            return None
        logger.info("[cover] Unsplash query=%r → %s (%d bytes)", query, out, out.stat().st_size)
        return out
    except Exception as exc:
        logger.warning("[cover] fetch failed: %s", exc)
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

        # Collect existing local stock images so note can re-host them
        # on its own CDN (assets.st-note.com/production/uploads) rather
        # than hotlinking Unsplash. Previously we relied on note's
        # clipboard-paste auto-rehost behaviour, which stopped working
        # reliably — the resulting body had plain Unsplash URLs only.
        # Path-traversal guard: the regex harvests paths from the
        # LLM-generated body, which a prompt-injection or malformed
        # source could use to smuggle ``data/images/../../.env`` and
        # exfiltrate a secret by uploading it to note. Only accept
        # paths that resolve inside the stock directory AND have an
        # allowed image extension.
        _stock_root = (Path.cwd() / "data" / "images" / "stock").resolve()
        _IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        inline_images: list[str] = []
        for m in re.finditer(r"!\[[^\]]*\]\((data/images/[^\s)]+)", content):
            p = Path(m.group(1))
            try:
                resolved = p.resolve()
            except Exception:
                continue
            if _stock_root not in resolved.parents and resolved.parent != _stock_root:
                logger.warning(
                    "[note] skipping out-of-root image path: %s", p,
                )
                continue
            if resolved.suffix.lower() not in _IMG_EXT:
                continue
            if resolved.exists() and resolved.stat().st_size > 0:
                inline_images.append(str(resolved))
        # Cap to avoid overloading the editor's paste buffer; hero +
        # first two section images is already visually rich.
        inline_images = inline_images[:4]
        if inline_images:
            logger.info("[note] note CDN にアップロードする画像 %d 件", len(inline_images))

        # Topic-themed cover from Unsplash. Falls back to None when
        # Unsplash is unreachable; publish_article will skip the
        # eyecatch step in that case.
        cover_path = _fetch_topic_cover(title)

        url = note_pub.publish_article(
            title=title,
            content=content,
            tags=tags,
            price=price,
            cover_image_path=str(cover_path) if cover_path else None,
            inline_image_paths=inline_images or None,
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

        # Run objective scoring on regenerated content. Share the
        # same normalization the initial-generation path uses so the
        # regen baseline doesn't silently drift (previously we only
        # looked at ``stored["source"]["sources"]`` and lost the
        # top-level URL/source_type for string-typed collector output).
        forbidden = config.get("evidence", {}).get("forbidden_phrases", [])
        sources = _normalize_sources_for_scoring(stored)

        chain_blacklist = config.get("evidence", {}).get(
            "gourmet_rules", {},
        ).get("chain_blacklist", [])

        obj_result = obj_scorer.score(content, {
            "sources": sources,
            "forbidden_phrases": forbidden,
            "chain_blacklist": chain_blacklist,
            "title": stored.get("title", ""),
            "platform": stored.get("platform", ""),
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

            # Update Sheets row with new scores. Previously we built
            # ``sheets_data`` but only called ``update_status`` — every
            # other column (grade, evidence, tier12_ratio, numeric
            # score, critic summary) stayed pinned to the pre-regen
            # values. Push the full row now that SheetsManager exposes
            # ``update_row``.
            sheets_data = final.get("for_sheets", {})
            if sheets_data:
                sheets_data["status"] = "⏳承認待ち"
                sheets_data["article_id"] = slug
                sheets_data["title"] = regen_title
                try:
                    sheets.update_row(article_id, sheets_data)
                except Exception as e:
                    logger.warning("Sheets row update failed: %s", e)
                    try:
                        sheets.update_status(article_id, "⏳承認待ち")
                    except Exception:
                        pass
            else:
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

_PIPELINE_LOCK_PATH = Path("data/.pipeline.lock")


def _acquire_pipeline_lock(mode: str) -> bool:
    """Claim an exclusive pipeline lock.

    Prevents Slack bot and manual CLI runs from racing on the same
    generate/publish cycle — previously this caused duplicate sheet
    rows and double-posted articles. Returns True on success.

    Stale locks (owner PID no longer running OR file older than 2h)
    are automatically reclaimed so a crashed run doesn't wedge the
    pipeline. `publish` mode is short-lived so it shares the same lock
    as `generate` — concurrent generate+publish is the main risk.
    """
    import os
    import time

    _PIPELINE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _stale(path: Path) -> bool:
        import errno
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return True
        age = time.time() - float(data.get("ts", 0))
        if age > 7200:  # 2h
            return True
        # PID-based check (Windows-friendly)
        pid = int(data.get("pid", 0))
        if pid <= 0:
            return True
        try:
            # os.kill with signal 0 raises if the process is gone.
            os.kill(pid, 0)
            return False
        except OSError as exc:
            # On Windows, kill(pid, 0) raises PermissionError (EPERM)
            # when the pid belongs to another user or a protected
            # process — the process exists, so the lock is NOT stale.
            # ESRCH means the pid really is gone.
            if exc.errno == errno.EPERM:
                return False
            return True

    if _PIPELINE_LOCK_PATH.exists():
        if not _stale(_PIPELINE_LOCK_PATH):
            try:
                info = json.loads(_PIPELINE_LOCK_PATH.read_text(encoding="utf-8"))
                logger.error(
                    "パイプラインロック取得失敗: 別実行中 "
                    "(pid=%s mode=%s started=%s)",
                    info.get("pid"), info.get("mode"), info.get("started"),
                )
            except Exception:
                logger.error("パイプラインロック取得失敗: ロックファイル読込不可")
            return False
        logger.warning("古いロックを検出、回収して継続")

    payload = {
        "pid": os.getpid(),
        "mode": mode,
        "ts": time.time(),
        "started": datetime.now().isoformat(),
    }
    _PIPELINE_LOCK_PATH.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )
    return True


def _release_pipeline_lock() -> None:
    """Delete the pipeline lock (safe to call when absent)."""
    try:
        _PIPELINE_LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("ロック解放失敗: %s", exc)


def run_pipeline(config: dict, prompts: dict, mode: str = "generate"):
    """メインパイプラインを実行する。

    Args:
        config: 設定dict。
        prompts: プロンプトテンプレートdict。
        mode: "generate"（生成+登録）or "publish"（承認済み投稿）。
    """
    if not _acquire_pipeline_lock(mode):
        # Refuse to start — another run owns the lock. Don't raise so
        # the Slack bot's error path stays clean; just log + return.
        return

    try:
        _run_pipeline_inner(config, prompts, mode)
    finally:
        _release_pipeline_lock()


def _run_pipeline_inner(config: dict, prompts: dict, mode: str):
    """Actual pipeline body — wrapped by run_pipeline for lock discipline."""
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
        "--cleanup-sheets", action="store_true",
        help="古い投稿済み/不合格行を削除してSheetsを整理",
    )
    parser.add_argument(
        "--keep-last", type=int, default=20,
        help="--cleanup-sheets で残す投稿済み/不合格の件数 (default 20)",
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
        # Expanded list so we capture the tag distribution for
        # women-facing topics too — previously only business/tech/ai/
        # money/lifestyle were scraped, which skewed the learned tag
        # pool toward finance/tech. Adding K-beauty, K-POP, fashion,
        # dieting, relationship, self-improvement categories gives the
        # prompt injection a broader surface for female-audience posts.
        for category in [
            "business", "tech", "ai", "money", "lifestyle",
            "美容", "コスメ", "韓国", "K-POP", "ダイエット",
            "ファッション", "恋愛", "自分磨き", "スキンケア",
        ]:
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

    # --- cleanup-sheets ---
    if args.cleanup_sheets:
        sheets = SheetsManager()
        stats = sheets.archive_old_rows(keep_last_n=args.keep_last)
        print(
            f"Sheets整理完了: 投稿済み削除={stats['main_deleted']} "
            f"不合格削除={stats['rejected_deleted']} "
            f"(各{args.keep_last}件保持)"
        )
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
