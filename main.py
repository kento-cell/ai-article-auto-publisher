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
import time
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
from generators.llm_config import get_llm
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
from utils.experiments import is_enabled as _xp_enabled
from utils.experiments import record_variant as _xp_record_variant

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

# Parallel cache holding the *structured* learn stats so
# ``_compute_learn_adoption`` can measure against the exact same set of
# top tags/phrases the prompt saw. Populated as a side-effect of
# ``_load_learned_block`` so the parsing cost is paid once.
_LEARN_STATS_CACHE: dict[str, dict] = {}


_LEARN_MERGE_WINDOW_DAYS = 7

_THUMBNAIL_LOG_PATH = Path("data/thumbnail_log.jsonl")


def _log_thumbnail_choice(title: str, query: str, path: str) -> None:
    """Append a single line to the thumbnail-choice JSONL so we can
    later correlate image queries with view / like counts.

    Not read by generation — this is the *data collection* half of
    the thumbnail-CTR learning loop. A future ``--learn`` run can
    cross-reference Sheets view/like stats against this log to
    surface which mood modifiers (pastel/neon/cinematic/…) drive
    the highest CTR per genre.

    Kept as JSONL (one record per line, no load/rewrite cycle) so
    concurrent generate runs don't race.
    """
    import json as _json
    from datetime import datetime as _dt

    record = {
        "ts": _dt.now().isoformat(),
        "title": title[:120],
        "image_query": query,
        "cover_path": path,
    }
    try:
        _THUMBNAIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_THUMBNAIL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("thumbnail log append failed: %s", exc)


def _compute_learn_adoption(
    content: str,
    tags: list[str] | None = None,
) -> dict:
    """Measure how strongly the generated article adopted the learn
    block hints.

    Three axes, all computed against the currently-merged learn
    statistics (loaded through ``_LEARN_STATS_CACHE``):

      * ``bracket_present``: does the title include the 【...】 bracket
        form that dominates the learn TOP10?
      * ``phrase_hits``: count of learn-report phrase markers (top-5
        ranked by real usage, with a 13-word canonical floor so a
        brand-new learn report with sparse phrase data still produces
        a non-degenerate metric). Sourced dynamically from the parsed
        learn stats instead of a hardcoded list.
      * ``tag_coverage_pct``: share of the *generated hashtags*
        overlapping with the learned top-tag set. Hashtags are taken
        from *tags* when supplied (the HashtagGenerator preview) —
        previously the code scanned the article body for ``#tags``,
        but note bodies carry no inline hashtags (note stores them on
        the article object), so the metric was stuck at 0.0%. When
        *tags* is None, falls back to body scan for backward compat.

    Returned values are informational — the caller stores them on the
    score dict but does not gate accept/reject on them.
    """
    import re as _re

    first_line = content.splitlines()[0] if content else ""
    bracket_present = bool(_re.search(r"【[^】]+】", first_line))

    # Ensure stats cache is primed (no-op on second call). The learn
    # block is also what the prompt saw, so adoption is measured
    # against the very same data the LLM was steered by.
    _load_learned_block()

    stats = _LEARN_STATS_CACHE.get("note", {})
    learned_phrase_raw = stats.get("top_phrases", [])
    learned_tag_set = set(stats.get("top_tags", []))

    # Learn reports encode phrase patterns as category labels such as
    # "まとめ・選" or "解説系". Normalize into searchable tokens by
    # splitting on common delimiters and stripping the "系" suffix so
    # ``in first_line`` actually matches. Keeps the metric honest when
    # the learn schema evolves: if future reports emit clean tokens,
    # this normalization is a no-op.
    import re as _re2
    _learned_phrase_tokens: set[str] = set()
    for raw in learned_phrase_raw:
        for tok in _re2.split(r"[・/,、\s]+", raw.strip()):
            tok = tok.rstrip("系").strip()
            if 1 <= len(tok) <= 8:
                _learned_phrase_tokens.add(tok)

    # Canonical floor: keep always-useful markers in the denominator so
    # a brand-new learn report with zero-parse phrases still produces
    # a meaningful ratio.
    canonical_floor = {
        "徹底", "完全", "保存版", "解説", "まとめ", "選",
        "狂気", "永久", "決定版", "朝メモ", "そもそも",
        "コアメンバー", "殿堂入り",
    }
    phrase_universe = _learned_phrase_tokens | canonical_floor
    phrase_hits = sum(1 for p in phrase_universe if p in first_line)

    # Tag coverage: prefer generator output, fall back to body scan.
    tag_coverage_pct = 0.0
    if tags:
        clean_tags = [t.lstrip("#").strip() for t in tags if t]
        if clean_tags and learned_tag_set:
            overlap = sum(1 for t in clean_tags if t in learned_tag_set)
            tag_coverage_pct = 100.0 * overlap / len(clean_tags)
    else:
        hashtag_matches = _re.findall(r"#(\w[\w_]{0,30})", content)
        if learned_tag_set and hashtag_matches:
            overlap = sum(
                1 for t in hashtag_matches if t in learned_tag_set
            )
            tag_coverage_pct = 100.0 * overlap / len(hashtag_matches)

    return {
        "bracket_present": bracket_present,
        "phrase_hits": phrase_hits,
        "phrase_total": len(phrase_universe),
        "tag_coverage_pct": round(tag_coverage_pct, 1),
    }


def _parse_learn_sections(text: str) -> dict[str, list[str]]:
    """Extract the bullet/numbered items from named sections of a
    single learn-report markdown.

    Returns a dict with keys ``top_titles``, ``phrases``, ``tags``.

    Accepts either H2 (``## ``) or H3 (``### ``) as the section
    boundary — learn reports put ``よく使われるパターン`` under H3 while
    ``トップ記事`` / ``タグ分布`` live at H2, and we want both.
    """
    def _is_heading(line: str) -> bool:
        return line.startswith(("## ", "### "))

    def _section(marker: str, limit: int) -> list[str]:
        lines = text.splitlines()
        out: list[str] = []
        in_sec = False
        for line in lines:
            if _is_heading(line):
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


def _load_success_patterns(max_chars: int = 900) -> str:
    """Read ``docs/knowledge/quality_successes.md`` (auto-generated by
    ``scripts/analyze_performance.py``) and return a prompt-injectable
    block listing the high-engagement title/structure patterns.

    Complementary to :func:`_load_failure_patterns` — same pipeline,
    opposite polarity. Together they form the self-improving quality
    loop: scrape performance → rank → emit success/failure patterns →
    inject into the note prompt on the next generation cycle.
    """
    path = Path("docs/knowledge/quality_successes.md")
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("success pattern read failed: %s", exc)
        return ""

    # Extract two key sections from the auto-generated file:
    #   "## 採用すべきタイトル型" and "## 採用すべき具体タイトル例".
    # We skip "last updated" / comment lines so the prompt stays tight.
    parts: list[str] = [
        "\n\n【エンゲージメント実績ベース — 真似すべき成功型】",
    ]
    in_shape = False
    in_examples = False
    bullet_count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## 採用すべきタイトル型"):
            in_shape = True
            in_examples = False
            bullet_count = 0
            parts.append("\n★ 実績上位で多いタイトル型:")
            continue
        if stripped.startswith("## 採用すべき具体タイトル例"):
            in_shape = False
            in_examples = True
            bullet_count = 0
            parts.append("\n★ 実績上位の具体タイトル例:")
            continue
        if stripped.startswith("## "):
            in_shape = False
            in_examples = False
            continue
        if (in_shape or in_examples) and stripped.startswith("- "):
            parts.append(stripped)
            bullet_count += 1
            if bullet_count >= 6:
                if in_shape:
                    in_shape = False
                else:
                    in_examples = False

    if len(parts) == 1:
        return ""  # Nothing useful found

    parts.append(
        "\n上記の型を踏襲しつつ、今回の記事内容に沿ったバリエーションで書くこと。"
    )
    block = "\n".join(parts) + "\n"
    if len(block) > max_chars:
        block = block[:max_chars] + "…\n"
    return block


def _load_anti_patterns(max_chars: int = 700) -> str:
    """Read ``docs/knowledge/quality_anti_patterns.md`` (auto-generated
    by ``scripts/analyze_performance.py``) and return a prompt-injectable
    block of engagement-failure title shapes the LLM should avoid.

    Counterpart to :func:`_load_success_patterns`: the success file lists
    shapes proven to drive likes; this one lists shapes that flopped on
    real reader data. Together they form a positive+negative feedback
    pair distinct from :func:`_load_failure_patterns` (which is about
    SCORING failures, not engagement failures).
    """
    path = Path("docs/knowledge/quality_anti_patterns.md")
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("anti-pattern read failed: %s", exc)
        return ""

    parts: list[str] = [
        "\n\n【エンゲージメント実績ベース — 避けるべきアンチパターン】",
    ]
    in_shape = False
    in_examples = False
    bullet_count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## 避けるべきタイトル型"):
            in_shape = True
            in_examples = False
            bullet_count = 0
            parts.append("\n✗ 下位20%に集中している型 (上位に出ない):")
            continue
        if stripped.startswith("## 避けるべき具体タイトル例"):
            in_shape = False
            in_examples = True
            bullet_count = 0
            parts.append("\n✗ 下位20%の具体タイトル例:")
            continue
        if stripped.startswith("## "):
            in_shape = False
            in_examples = False
            continue
        if (in_shape or in_examples) and stripped.startswith("- "):
            parts.append(stripped)
            bullet_count += 1
            if bullet_count >= 5:
                if in_shape:
                    in_shape = False
                else:
                    in_examples = False

    if len(parts) == 1:
        return ""

    parts.append(
        "\n上記の型は実績で読者が反応しなかったので避けること。"
        "似た切り口を採るなら別の型・別の表現で。"
    )
    block = "\n".join(parts) + "\n"
    if len(block) > max_chars:
        block = block[:max_chars] + "…\n"
    return block


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


def _check_topic_duplication(
    title: str,
    promise: str = "",
    top_k: int = 3,
    # Tuned 2026-05-11: same article re-titled scores ~0.93+ on
    # multilingual-e5-base. Distinct articles in the same genre
    # ("AI副業 ライティング" vs "AI副業 30日ロードマップ") score
    # ~0.78-0.85. 0.88 catches near-duplicates without false-flagging
    # legitimate companion pieces.
    score_threshold: float = 0.88,
) -> list[dict]:
    """Sprint 3 (2026-05-11) — surface near-duplicate past articles.

    Returns a list of records ``{score, title, source_file}`` for past
    articles whose title+summary semantically match the proposed topic
    above ``score_threshold``. Empty list when:
      - ``RAG_DUPLICATE_CHECK=false`` env override, OR
      - index missing, OR
      - no hit clears the threshold.

    The current pipeline only *logs* the result — no automatic
    rejection — so operator can decide whether the new piece is a
    legit follow-up or a true duplicate. Per 2026-05-11 requirements
    doc, automatic blocking is deferred until false-positive rate is
    measured.
    """
    if os.environ.get("RAG_DUPLICATE_CHECK", "true").lower() in (
        "false", "0", "no", "off",
    ):
        return []
    try:
        from generators.rag_retriever import RagRetriever
    except ImportError:
        return []
    query = (title.strip() + " " + (promise or "").strip()).strip()
    if not query:
        return []
    try:
        retriever = RagRetriever()
        hits = retriever.retrieve(
            query=query,
            collection="past_articles",
            top_k=top_k,
            score_threshold=score_threshold,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("duplicate check retrieval failed: %s", exc)
        return []
    if not hits:
        return []
    flagged = []
    for h in hits:
        flagged.append(
            {
                "score": h.score,
                "title": (h.metadata.get("section_title", "")
                          if h.metadata else "")[:120],
                "source_file": (h.metadata.get("source_file", "")
                                if h.metadata else ""),
            }
        )
    logger.warning(
        "[dup-check] new topic %r matches %d past article(s) >= %.2f",
        title[:80], len(flagged), score_threshold,
    )
    for f in flagged:
        logger.warning(
            "  similar: (sim %.3f) %s",
            f["score"], f["title"],
        )
    return flagged


def _build_rag_learned_block(
    query_seed: str,
    platform: str,
    top_k_each: int = 3,
    score_threshold: float = 0.55,
) -> str:
    """RAG-augmented replacement for ``_load_learned_block``.

    Sprint 4 (2026-05-11): when ``RAG_ENABLED=true`` is set, the
    generation prompt's "learned patterns" block is built by semantic
    retrieval over the ``anti_patterns`` and ``successes`` collections
    instead of dumping the full static markdown. This narrows the LLM's
    attention to patterns actually relevant to the topic at hand, which
    should reduce both prompt-token cost and the "ignore the noise"
    failure mode (cf. 2026-05-11 H2 全滅 incident).

    The static path remains the default — the flag must be set
    explicitly. Returns "" silently when:
      - flag is off, OR
      - RAG deps / index are missing, OR
      - no chunks clear ``score_threshold``.
    """
    if os.environ.get("RAG_ENABLED", "false").lower() not in (
        "true", "1", "yes", "on",
    ):
        return ""
    try:
        from generators.rag_retriever import RagRetriever
    except ImportError:
        return ""
    try:
        retriever = RagRetriever()
        hits = retriever.retrieve_many(
            query=query_seed,
            plan=[
                ("anti_patterns", top_k_each),
                ("successes", top_k_each),
            ],
            score_threshold=score_threshold,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("RAG learned-block retrieval failed: %s", exc)
        return ""

    anti_hits = hits.get("anti_patterns", [])
    succ_hits = hits.get("successes", [])
    if not anti_hits and not succ_hits:
        return ""

    parts: list[str] = ["\n## 学習済みパターン (この記事に関連性 0.55+)\n"]
    if succ_hits:
        parts.append("### マネすべき (上位エンゲ実績)")
        for h in succ_hits:
            section = h.metadata.get("section_title", "") if h.metadata else ""
            snippet = h.text.strip().replace("\n", " ")[:240]
            parts.append(f"- (sim {h.score:.2f}) {section}: {snippet}")
        parts.append("")
    if anti_hits:
        parts.append("### 避けるべき (下位エンゲ実績)")
        for h in anti_hits:
            section = h.metadata.get("section_title", "") if h.metadata else ""
            snippet = h.text.strip().replace("\n", " ")[:240]
            parts.append(f"- (sim {h.score:.2f}) {section}: {snippet}")
        parts.append("")
    parts.append(
        "上記の「マネすべき」型を骨格に、「避けるべき」型は決して使わずに書くこと。"
    )
    block = "\n".join(parts) + "\n"
    logger.info(
        "[rag-learn:%s] success=%d, anti=%d (block=%d chars)",
        platform, len(succ_hits), len(anti_hits), len(block),
    )
    return block


def _retrieve_hallucination_warnings(
    article_content: str,
    top_k: int = 3,
    # Threshold tuned 2026-05-11 against the chromadb seed (22 chunks).
    # At 0.62 a clean tech article describing Claude/AI topically came
    # back with 3 false-positive hits at cos sim ~0.82. The planted
    # hallucination ("〇〇寿司") scored 0.89-0.91. 0.85 cleanly separates
    # them. Revisit when the index grows past 100 chunks.
    score_threshold: float = 0.85,
) -> list[dict]:
    """RAG-driven hallucination guard for the subjective critic.

    Sprint 2 (2026-05-11): given an article body, semantic-search the
    hallucinations collection for past incidents that look similar, and
    return a compact warning record per hit. The critic prompt receives
    these and is instructed to downgrade accuracy/title_fulfillment to
    C if the current article reproduces any of the patterns.

    Returns an empty list when:
      - ``RAG_HALLUCINATION_CHECK=false`` is set explicitly, OR
      - the chromadb index hasn't been built yet, OR
      - chromadb / sentence-transformers aren't installed, OR
      - no hit clears ``score_threshold``.

    All failures are silent so the existing pipeline never breaks
    because of this guard.
    """
    if os.environ.get("RAG_HALLUCINATION_CHECK", "true").lower() in (
        "false", "0", "no", "off",
    ):
        return []
    try:
        from generators.rag_retriever import RagRetriever
    except ImportError:
        return []
    try:
        retriever = RagRetriever()
        # Use a representative chunk of the article (start + middle)
        # so the query embedding captures both the lede (where most
        # hallucination patterns live: 〇〇店, AI開示) AND the body
        # (where evidence-free claims may appear).
        body = article_content[:1500]
        mid_start = max(0, len(article_content) // 2 - 500)
        mid = article_content[mid_start: mid_start + 1000]
        query = (body + "\n" + mid)[:3000]
        hits = retriever.retrieve(
            query=query,
            collection="hallucinations",
            top_k=top_k,
            score_threshold=score_threshold,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("hallucination retrieval failed: %s", exc)
        return []
    warnings: list[dict] = []
    for h in hits:
        warnings.append(
            {
                "score": h.score,
                "section_title": h.metadata.get("section_title", "")
                if h.metadata else "",
                "snippet": (h.text or "").strip().replace("\n", " ")[:240],
            }
        )
    if warnings:
        logger.info(
            "[hallu-guard] %d past incident(s) flagged for critic review",
            len(warnings),
        )
    return warnings


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

        # Stash the parsed stats alongside the formatted block so
        # ``_compute_learn_adoption`` can measure against the same
        # top-phrase / top-tag set the prompt saw.
        _LEARN_STATS_CACHE["note"] = {
            "top_phrases": [p for p, _ in phrases_ranked],
            "top_tags": [t for t, _ in tags_ranked],
            "top_titles": merged_titles[:10],
        }

        # Append the failure-pattern block so the LLM avoids known
        # traps. Gated so A/B runs can isolate its contribution.
        if _xp_enabled("learn.failure_patterns"):
            block += _load_failure_patterns()

        # Append the success-pattern block — closes the quality loop
        # added 2026-04-23 (scripts/analyze_performance.py). LLM gets
        # both "avoid these traps" (failures) and "match these shapes"
        # (successes) so the next generation converges toward proven
        # engagement patterns.
        if _xp_enabled("learn.success_patterns"):
            block += _load_success_patterns()

        # Append the engagement-driven anti-pattern block: shapes that
        # appear in the bottom 20% AND never in the top 20% on real
        # reader data. Distinct from learn.failure_patterns (which is
        # about scoring failures, not engagement).
        if _xp_enabled("learn.anti_patterns"):
            block += _load_anti_patterns()
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


_AI_DISCLAIMER_SENTINEL = "<!-- STORE_DATA_DISCLAIMER -->"
# 2026-05-08 改訂: 旧文面 "本記事の店舗情報は…AIが構成しています" は
# (a) 店舗情報がない技術記事にも誤って付き、(b) "AIが構成" という
# AI 開示文言が読者への裏切り(品質を担保していない=逃げ口上)になるため、
# 文面を「営業時間/価格は変動する可能性」だけに絞り、AI 言及を削除。
# さらに STORE_BLOCK_START sentinels を含む「実店舗を扱う記事」だけに
# 限定して付与する (一般記事には付かない)。
_AI_DISCLAIMER_BLOCK = f"""
---

{_AI_DISCLAIMER_SENTINEL}
## ご利用にあたって

本記事に掲載した店舗の営業時間・価格・メニューは、変更される場合があります。来店前に公式サイトまたは店舗へ直接ご確認ください。
"""


def _has_store_blocks(content: str) -> bool:
    """True iff the article contains real STORE_BLOCK sentinels."""
    return "STORE_BLOCK_START" in content


def _ensure_ai_disclaimer(content: str) -> str:
    """Append the data-staleness disclaimer ONLY for store/施設 articles.

    Conditions:
    1. Article contains STORE_BLOCK sentinels (real stores being referenced).
    2. No existing 免責 / disclaimer heading (idempotent).

    Tech / AI tool / general articles do NOT get a disclaimer.
    """
    if _AI_DISCLAIMER_SENTINEL in content:
        return content
    # Skip if the article doesn't actually reference stores.
    if not _has_store_blocks(content):
        return content
    # LLM-authored disclaimers usually use "免責事項" as the H2.
    if re.search(r"(?m)^#{1,3}.{0,6}免責", content):
        return content
    if re.search(r"(?m)^#{1,3}.{0,6}ご利用にあたって", content):
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


# ---------------------------------------------------------------------------
# Image mood modifiers — "eye-catching image" aesthetic per genre
# ---------------------------------------------------------------------------
# Unsplash / Pexels return very different photos for
# "k-pop idol" vs "k-pop idol stage glamour"; the modifier is where
# CTR lives. We stamp a mood tag onto every query based on the
# article's detected genre so cosmetics posts get soft pastel shots,
# AI sidegigs get sleek futuristic shots, and male-targeted finance /
# gadget posts get bold cinematic shots.
#
# Each entry: (regex on title+body, mood modifier appended to query).
# First match wins, ordered most specific → most general.
_IMAGE_MOOD_RULES: list[tuple[str, str]] = [
    # Entertainment / comedy / voice actor / celebrity — high priority
    # so an LLM hallucination that smuggles "美容室" or "コスメ" into a
    # 令和ロマン / 花澤香菜 article doesn't make the image query bleed
    # into K-beauty territory (see 2026-04-23 incident).
    (r"お笑い|漫才|コント|芸人|M-?1|R-?1|キングオブコント|"
     r"令和ロマン|霜降り明星|ミルクボーイ|錦鯉|ランジャタイ",
     "comedy stage spotlight crowd"),
    (r"声優|アニメ|ラノベ|劇場版|映画|ドラマ|俳優|女優",
     "studio microphone cinematic spotlight"),

    # Female-targeted aesthetics — cosmetics, K-beauty, K-POP idol,
    # femaleinterest lifestyle, dieting / self-care.
    (r"コスメ|美容|スキンケア|メイク|化粧|美白|保湿|美活",
     "aesthetic soft pastel feminine"),
    (r"K-?POP|韓国アイドル|BTS|BLACKPINK|NewJeans|aespa|IVE|ITZY",
     "glamour stage lights pastel"),
    (r"韓国|韓流|kbeauty|k-?beauty",
     "seoul pastel aesthetic neon"),
    (r"ダイエット|自分磨き|垢抜け|ボディメイク",
     "wellness aesthetic pastel soft"),
    (r"恋愛|婚活|結婚",
     "romantic couple soft pastel"),
    (r"ファッション|コーデ|アパレル",
     "fashion magazine editorial pastel"),
    (r"ネイル|ヘアケア|まつエク",
     "pastel aesthetic beauty close-up"),

    # Food & gourmet — bright, high-appetite appeal.
    (r"焼肉|和牛|ステーキ",
     "cinematic close-up sizzling warm"),
    (r"ラーメン|つけ麺|担々麺",
     "noodle bowl steam moody lighting"),
    (r"カフェ|コーヒー|喫茶",
     "aesthetic morning light cozy"),
    (r"寿司|和食|懐石",
     "minimal elegant japanese plating"),
    (r"スイーツ|パフェ|ケーキ",
     "dessert pastel cute studio lighting"),
    (r"カレー|スパイス",
     "warm curry spice market"),

    # Tech / AI / engineering — male-targeted, bold, futuristic.
    (r"AI副業|マネタイズ|収益化|稼ぐ|副業",
     "laptop neon night entrepreneur"),
    (r"AI|ChatGPT|Claude|LLM|機械学習",
     "futuristic neon dark tech"),
    (r"エンジニア|プログラミング|コード",
     "dark ide monitor glow"),
    (r"ガジェット|レビュー|デバイス",
     "product cinematic studio lighting"),
    (r"セキュリティ|ハッキング|サイバー",
     "dark hacker code green matrix"),
    (r"クラウド|AWS|GCP|Azure",
     "datacenter blue server rack"),

    # Finance / business — aspirational, serious.
    (r"投資|株|資産|不動産|仮想通貨|ビットコイン",
     "bull market skyscraper dusk"),
    (r"起業|スタートアップ|経営",
     "executive office cinematic city"),

    # Politics / international.
    (r"政治|選挙|首相|大統領|外交",
     "newsroom professional serious"),
    (r"中国|北京|習近平",
     "beijing cityscape dusk"),
    (r"韓国|ソウル|大統領",
     "seoul hanok modern mix"),

    # Sports.
    (r"NBA|バスケ|バスケット",
     "basketball arena stage lights"),
    (r"サッカー|フットボール",
     "stadium night floodlight"),
    (r"野球|MLB|ベースボール",
     "baseball stadium evening"),

    # Travel / cityscape.
    (r"旅行|観光|ホテル|リゾート",
     "travel golden hour cinematic"),

    # Music / entertainment (non-KPOP fallback).
    (r"音楽|ライブ|コンサート|歌手",
     "concert stage spotlights moody"),

    # Medical / clinic.
    (r"美容皮膚科|ダーマペン|エクソソーム|HIFU|美容医療",
     "clinic aesthetic soft premium"),
    (r"病院|診療|医療|クリニック",
     "medical clean white minimal"),
]


def _image_mood_modifier(title: str, content: str = "") -> str:
    """Return an Unsplash-friendly mood phrase based on the article's
    detected genre. Empty string when no rule matches; caller appends
    it to the base topical query.
    """
    hay = f"{title}\n{content[:600]}"
    for pattern, mood in _IMAGE_MOOD_RULES:
        if re.search(pattern, hay, re.IGNORECASE):
            return mood
    return ""


#
# Order matters — earlier entries win the first-match. Put SPECIFIC
# subjects (skincare, robotics, coffee extraction) BEFORE generic
# umbrellas (韓国, AI, 音楽). Otherwise a K-beauty skincare article
# matches "韓国 → korea seoul" and gets Seoul cherry-blossom photos
# instead of skincare; a 休息 (rest) article matches "rest → at rest"
# tombstones; etc. Each entry's English value should evoke the actual
# physical subject, not the umbrella topic.
#
_THEME_KEYWORDS: list[tuple[str, str]] = [
    # Specific subjects first — these MUST win over umbrella terms.
    ("スキンケア", "skincare cosmetics bottle"),
    ("化粧水", "skincare cosmetics bottle"),
    ("美容液", "skincare serum bottle"),
    ("クレンジング", "skincare cleansing"),
    ("洗顔", "skincare face wash"),
    ("保湿", "skincare moisturizer"),
    ("角質", "skincare face care"),
    ("肌荒れ", "skincare face care"),
    ("肌質", "skincare face care"),
    ("K-beauty", "skincare cosmetics bottle"),
    ("Kビューティー", "skincare cosmetics bottle"),
    ("メイク", "makeup cosmetics"),
    ("リップ", "lipstick cosmetics"),
    # Coffee subjects — must beat generic "コーヒー" because the broader
    # term often pulls cafe interiors when we want bean / extraction
    # close-ups.
    ("焙煎", "coffee beans roasting"),
    ("抽出", "coffee pour over brewing"),
    ("カッピング", "coffee tasting cupping"),
    ("ドリップ", "coffee dripper pour over"),
    ("豆", "coffee beans roasted"),
    ("ロースター", "coffee roastery beans"),
    ("バリスタ", "barista coffee shop"),
    ("コーヒー", "coffee beans cup"),
    ("カフェ", "cafe interior coffee"),
    # Time / focus / rest / habit — the 'rest' query MUST NOT collide
    # with English "at rest" tombstone photography.
    ("朝活", "morning routine sunrise"),
    ("ルーティン", "morning routine notebook"),
    ("習慣", "morning routine notebook"),
    ("タイムブロッキング", "calendar planner schedule"),
    ("ポモドーロ", "timer desk focus"),
    ("Deep Work", "focused work desk laptop"),
    ("時間管理", "calendar planner schedule"),
    ("休息", "relax peaceful tea"),
    ("リラックス", "relax peaceful tea"),
    ("ストレス", "calm meditation peaceful"),
    ("瞑想", "meditation calm peaceful"),
    ("睡眠", "bedroom sleep cozy"),
    # Robotics / VLA — pulled subject before AI umbrella so 論文 articles
    # get robot arms instead of generic AI brain renders or coding.
    ("ロボット", "robot arm robotics"),
    ("ロボティクス", "robot arm robotics"),
    ("Figure", "humanoid robot lab"),
    ("Tesla", "humanoid robot lab"),
    ("Neo", "humanoid robot home"),
    ("ヒューマノイド", "humanoid robot lab"),
    ("VLA", "robot arm laboratory"),
    ("マニピュレ", "robot arm gripping"),
    ("把持", "robot gripper hand"),
    # Food (specific before umbrella).
    ("ラーメン", "ramen bowl noodles"),
    ("寿司", "sushi platter japan"),
    ("スイーツ", "dessert pastry plate"),
    ("焼肉", "yakiniku grill meat"),
    ("カレー", "curry spice plate"),
    ("ランチ", "japanese restaurant table"),
    ("居酒屋", "japanese izakaya bar"),
    ("グルメ", "japanese food close up"),
    # Music.
    ("歌手", "concert stage lights"),
    ("アーティスト", "music studio recording"),
    ("音楽", "music studio recording"),
    ("ライブ", "concert stage crowd"),
    # Sports.
    ("NBA", "basketball game arena"),
    ("バスケ", "basketball court arena"),
    ("サッカー", "soccer stadium pitch"),
    ("野球", "baseball stadium pitch"),
    # Programming subjects (specific before AI umbrella).
    ("Python", "python code editor"),
    ("React", "web development laptop"),
    ("TypeScript", "code editor screen"),
    ("hooks", "code editor screen"),
    ("MCP", "code editor terminal"),
    ("settings.json", "code editor terminal"),
    # Travel / locale (LAST among umbrellas — easily misfires).
    ("旅行", "japan travel landmark"),
    ("観光", "japan travel landmark"),
    ("テーマパーク", "amusement park ride"),
    ("ディズニー", "amusement park castle"),
    ("地下鉄", "tokyo subway station"),
    ("鉄道", "japan train station"),
    ("電車", "japan train station"),
    # Politics / business.
    ("投資", "stock chart finance"),
    ("株価", "stock chart finance"),
    ("副業", "laptop home desk"),
    ("マネタイズ", "money business desk"),
    ("起業", "startup laptop desk"),
    ("政治", "japanese parliament"),
    ("首相", "japanese parliament"),
    # Generic AI / LLM — LAST. These are too broad on their own but
    # serve as a final umbrella when nothing more specific matched.
    ("Claude", "ai technology laptop"),
    ("ChatGPT", "ai technology laptop"),
    ("LLM", "ai technology laptop"),
    ("論文", "research paper desk"),
    ("機械学習", "machine learning chart"),
    ("AI", "artificial intelligence abstract"),
    # Korea — stays at the very END as a fallback. Only fires when
    # NOTHING above matched, which avoids the K-beauty article ending
    # up with Seoul cityscapes.
    ("韓国", "korea seoul city"),
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

    # Compose the topic keywords, then append a genre-aware mood phrase
    # so Unsplash / Pexels return *eye-catching* shots instead of
    # generic stock. Rules live in ``_IMAGE_MOOD_RULES`` — cosmetics
    # gets soft/pastel, AI sidegig gets neon/dark, K-POP gets
    # glamour/stage-lights, etc.
    mood = _image_mood_modifier(title, content)

    if keywords:
        base = " ".join(keywords[:3])
        return f"{base} {mood}".strip() if mood else base

    # 4. Last resort: domain-guessed fallback from title+content.
    hay = combined_for_theme
    fallback = "lifestyle"
    if any(w in hay for w in ("AI", "ＡＩ", "LLM", "モデル", "論文")):
        fallback = "technology ai"
    elif any(w in hay for w in ("店", "グルメ", "食", "メニュー", "ラーメン")):
        fallback = "food restaurant"
    elif any(w in hay for w in ("韓国", "K-POP", "アイドル")):
        fallback = "korea seoul city"
    elif any(w in hay for w in ("音楽", "歌", "シンガー", "ライブ")):
        fallback = "music concert stage"
    elif any(w in hay for w in ("スポーツ", "試合", "選手")):
        fallback = "sports stadium"
    return f"{fallback} {mood}".strip() if mood else fallback


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


# Tokens that, when present in alt text WITHOUT matching the article,
# strongly indicate a hallucinated image — the historical failure
# modes (休息→tombstone, スキンケア→Seoul cherry blossom, ロースター→
# sewing machine). If alt contains any of these AND the article does
# not, drop the image. This is a backstop when query extraction
# itself doesn't catch the mismatch.
_ALT_RED_FLAGS: dict[str, frozenset[str]] = {
    # Death imagery on rest / habit / morning articles.
    "tombstone": frozenset({"墓", "葬", "霊"}),
    "gravestone": frozenset({"墓", "葬", "霊"}),
    "grave": frozenset({"墓", "葬", "霊"}),
    "cemetery": frozenset({"墓", "葬", "霊"}),
    "headstone": frozenset({"墓", "葬", "霊"}),
    "at rest": frozenset({"墓", "葬", "霊"}),
    "rip": frozenset({"墓", "葬", "霊"}),
    "buried": frozenset({"墓", "葬", "霊"}),
    "funeral": frozenset({"墓", "葬", "霊"}),
    # Sewing / textile imagery for coffee / AI articles.
    "sewing machine": frozenset({"裁縫", "ミシン", "服飾"}),
    "thread": frozenset({"裁縫", "ミシン"}),
    "fabric": frozenset({"裁縫", "ミシン", "服飾"}),
    # Tombstone/coffin trigger words.
    "coffin": frozenset({"棺", "葬"}),
    "tomb": frozenset({"墓", "葬"}),
    # Toothbrush / dental for non-dental articles.
    "toothbrush": frozenset({"歯", "デンタル", "口腔"}),
    "dental": frozenset({"歯", "デンタル", "口腔"}),
    # Boats for non-marine articles.
    "boat": frozenset({"船", "海", "ヨット", "クルーズ"}),
    "yacht": frozenset({"船", "海", "ヨット", "クルーズ"}),
    "sailing": frozenset({"船", "海", "ヨット"}),
    # Mannequin / display dummy for non-fashion articles.
    "mannequin": frozenset({"ファッション", "服", "アパレル", "店頭"}),
    # VR / sci-fi cosplay for non-VR articles.
    "vr headset": frozenset({"VR", "メタバース", "AR", "XR"}),
    "sci-fi": frozenset({"SF", "アニメ", "コスプレ"}),
    "cosplay": frozenset({"コスプレ", "アニメ"}),
    "armor": frozenset({"鎧", "ファンタジー"}),
    # Concert / stage for non-music articles.
    "concert stage": frozenset({"音楽", "ライブ", "コンサート", "歌手", "アーティスト"}),
    "soundboard": frozenset({"音楽", "ライブ", "ミキサー"}),
    # Cherry blossom / Seoul scenery for non-travel articles.
    "cherry blossom": frozenset({"桜", "花見", "春", "観光", "旅行"}),
    "seoul": frozenset({"ソウル", "韓国", "観光", "旅行", "K-POP"}),
}


def _alt_is_relevant(alt: str, title: str, content: str) -> bool:
    """Return True if `alt` looks safe to insert into an article whose
    `title` + `content` do not contain the disqualifying themes from
    `_ALT_RED_FLAGS`. False means the image is almost certainly a
    hallucination (gravestones on a 'rest' article etc.) and should
    be dropped silently.
    """
    if not alt:
        return True
    alt_lo = alt.lower()
    haystack = f"{title}\n{content[:2000]}".lower()
    for flag, allowed in _ALT_RED_FLAGS.items():
        if flag not in alt_lo:
            continue
        # If any of the article's tokens explicitly endorses this
        # subject (e.g. 葬儀 article featuring tombstone), allow it.
        if any(a.lower() in haystack for a in allowed):
            return True
        logger.warning(
            "[image] dropping hallucinated alt=%r — red flag %r without matching subject in article",
            alt[:80],
            flag,
        )
        return False
    return True


# Subject-vocabulary expansion. The query we send to Unsplash/Pexels
# resolves to a 1-3 word English phrase (e.g. "skincare cosmetics
# bottle"). We then check the returned image's alt text for at least
# one *related* English word — a coffee article should yield alts
# mentioning {coffee, cafe, espresso, bean, …}, a robotics article
# should yield {robot, machine, arm, automation, …}. When the alt has
# zero overlap with the expected vocabulary, the image is almost
# certainly off-topic even if it didn't trip a red flag, and we drop
# it. This is a positive-side companion to `_ALT_RED_FLAGS`.
#
# Mapping is keyed by lower-case substrings that appear in our query
# strings; values are the set of words that should at least partially
# show up in a relevant alt text.
_QUERY_SUBJECT_VOCAB: list[tuple[str, frozenset[str]]] = [
    ("skincare", frozenset({
        "skin", "skincare", "cosmetic", "cosmetics", "makeup", "beauty",
        "lip", "lipstick", "face", "facial", "bottle", "serum", "lotion",
        "cream", "moisturiz", "moisturis", "powder", "fragrance", "spa",
    })),
    ("cosmetic", frozenset({
        "cosmetic", "cosmetics", "makeup", "beauty", "lip", "lipstick",
        "face", "powder", "skincare", "fragrance",
    })),
    ("coffee", frozenset({
        "coffee", "cafe", "espresso", "latte", "bean", "beans", "brew",
        "brewing", "barista", "cup", "mug", "kettle", "pour", "drip",
        "roast", "roasting", "roaster", "roastery", "moka",
    })),
    ("robot", frozenset({
        "robot", "robotic", "machine", "arm", "drone", "automation",
        "automate", "mechanical", "gripper", "industrial", "factory",
        "engineer", "humanoid",
    })),
    ("morning routine", frozenset({
        "morning", "sunrise", "breakfast", "coffee", "bedroom", "alarm",
        "sun", "dawn", "daybreak", "tea", "kitchen", "window",
    })),
    ("calendar", frozenset({
        "calendar", "schedule", "clock", "planner", "watch", "agenda",
        "time", "desk", "notebook", "diary", "journal",
    })),
    ("planner", frozenset({
        "planner", "calendar", "notebook", "diary", "journal", "agenda",
        "schedule", "desk", "pen", "list",
    })),
    ("relax", frozenset({
        "tea", "candle", "plant", "calm", "peaceful", "meditation",
        "yoga", "spa", "bath", "blanket", "cozy", "relax", "sofa",
        "couch", "book", "garden",
    })),
    ("meditation", frozenset({
        "meditation", "yoga", "calm", "peaceful", "lotus", "mindful",
        "breathe", "incense", "candle",
    })),
    ("ramen", frozenset({"ramen", "noodle", "noodles", "soup", "bowl"})),
    ("sushi", frozenset({"sushi", "sashimi", "rice", "fish", "japanese"})),
    ("ai technology", frozenset({
        "ai", "tech", "computer", "laptop", "desk", "code", "screen",
        "monitor", "neural", "circuit", "robot", "device", "office",
        "workspace", "keyboard", "typing",
    })),
    ("artificial intelligence", frozenset({
        "ai", "tech", "computer", "laptop", "code", "screen", "neural",
        "circuit", "abstract", "digital", "data",
    })),
    ("python code", frozenset({
        "code", "coding", "programming", "computer", "laptop", "screen",
        "developer", "monitor", "keyboard",
    })),
    ("web development", frozenset({
        "code", "coding", "computer", "laptop", "screen", "developer",
        "web", "monitor", "keyboard", "design",
    })),
    ("machine learning", frozenset({
        "data", "chart", "computer", "graph", "ai", "neural", "circuit",
        "abstract", "tech",
    })),
    ("stock chart", frozenset({
        "stock", "chart", "graph", "trading", "finance", "market",
        "money", "data", "candlestick",
    })),
    ("finance", frozenset({
        "finance", "money", "stock", "chart", "graph", "bank", "wallet",
        "coin", "currency", "office",
    })),
    ("startup", frozenset({
        "startup", "office", "team", "laptop", "desk", "meeting",
        "whiteboard", "co-working", "coworking", "workspace",
    })),
    ("concert", frozenset({
        "concert", "stage", "music", "guitar", "band", "audience",
        "live", "festival", "lights",
    })),
    ("music", frozenset({
        "music", "guitar", "piano", "studio", "headphones", "vinyl",
        "concert", "band", "song", "instrument",
    })),
    ("basketball", frozenset({
        "basketball", "court", "ball", "arena", "player", "hoop",
        "athlete", "sport",
    })),
    ("soccer", frozenset({
        "soccer", "football", "stadium", "pitch", "ball", "player",
        "athlete", "sport",
    })),
    ("baseball", frozenset({
        "baseball", "stadium", "pitch", "bat", "player", "athlete",
        "sport",
    })),
    ("travel", frozenset({
        "travel", "city", "landmark", "tourism", "tourist", "japan",
        "tokyo", "street", "view", "skyline", "tower", "shrine",
    })),
    ("subway", frozenset({
        "subway", "train", "station", "metro", "platform", "rail",
        "tokyo",
    })),
    ("train station", frozenset({
        "train", "station", "subway", "metro", "platform", "rail",
        "japan", "tokyo",
    })),
    ("amusement park", frozenset({
        "park", "ride", "rollercoaster", "castle", "ferris", "amusement",
        "theme",
    })),
    ("korea", frozenset({
        "korea", "korean", "seoul", "k-pop", "kpop", "hanok", "palace",
        "street", "city",
    })),
]


def _alt_matches_query_subject(alt: str, query: str) -> bool:
    """Return True if `alt` contains at least one expected vocabulary
    word for the given image-search `query`. False = the image is
    plausibly off-topic even though it didn't trigger a red flag.

    Always returns True when no vocabulary mapping exists for any
    query token (we don't want to drop images when we have no opinion
    about what they should look like).
    """
    if not alt or not query:
        return True
    alt_lo = alt.lower()
    query_lo = query.lower()
    matched_any_rule = False
    for key, vocab in _QUERY_SUBJECT_VOCAB:
        if key not in query_lo:
            continue
        matched_any_rule = True
        if any(w in alt_lo for w in vocab):
            return True
    if matched_any_rule:
        logger.warning(
            "[image] dropping off-subject alt=%r — query=%r expected vocab not in alt",
            alt[:80],
            query,
        )
        return False
    # No rule triggered → we have no opinion → keep.
    return True


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

    # Filter out placeholder/empty results AND alt-text red flags
    # (gravestones on a rest article, sewing machines on a coffee
    # article, etc. — see `_alt_is_relevant` docstring), AND alts
    # that simply don't carry the subject vocabulary the query asked
    # for (a robotics query that returned a "man on a beach" alt is
    # almost certainly off-topic — see `_alt_matches_query_subject`).
    usable = [
        img
        for img in images
        if img.get("url")
        and img.get("platform") != "Placeholder"
        and _alt_is_relevant(img.get("alt_text", ""), title, content)
        and _alt_matches_query_subject(img.get("alt_text", ""), query)
    ]
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

    # Insert into markdown.
    #
    # LLM (Gemma3) frequently demotes body sections to ``### 1.`` /
    # ``### 2.`` H3s even when the prompt asks for H2s. Articles with
    # only 2-3 literal ``##`` headings (福岡市/ノジマ電気 2026-04-23)
    # ended up with just 2 images because the old loop only counted
    # H2s. Treat H3 numbered list sections as structural H2 for the
    # purpose of image placement so inline image count stays healthy.
    lines = content.split("\n")
    out: list[str] = []
    section_seen = 0
    hero_inserted = False
    section_idx = 0
    _numbered_h3_re = re.compile(r"^###\s+\d+[\.\s]")

    for line in lines:
        is_h2 = line.startswith("## ")
        is_numbered_h3 = bool(_numbered_h3_re.match(line))
        is_section = is_h2 or is_numbered_h3
        if is_section:
            section_seen += 1
            # Insert section image BEFORE every other section past the
            # first (greedier than the old "every 2nd H2 starting at #3"
            # rule — the old rule needed ≥7 H2s to place all 3 images).
            if (
                section_seen >= 2
                and (section_seen % 2) == 0
                and section_idx < len(section_blocks)
            ):
                out.append("")
                out.append(section_blocks[section_idx])
                section_idx += 1
            out.append(line)
            # Insert hero image AFTER first section heading.
            if not hero_inserted and section_seen == 1:
                out.append("")
                out.append(hero_block)
                hero_inserted = True
        else:
            out.append(line)

    # If no section heading was found at all, prepend hero at the top.
    if not hero_inserted:
        out = [hero_block, ""] + out

    # Flush any remaining section images at the end so the article
    # doesn't get shortchanged on inline images just because the LLM
    # produced few structural headings.
    while section_idx < len(section_blocks):
        out.append("")
        out.append(section_blocks[section_idx])
        section_idx += 1

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

    # Google Trends: disabled as a note source (2026-04-23).
    # Rationale: owner's editorial direction is self-help / knowledge
    # sharing — not breaking news. Trends fed raw celebrity names
    # (花澤香菜, 令和ロマン, ソフトバンク株価, サンケイビル) that the LLM
    # could not responsibly write about without fact base, producing
    # hallucinated placeholder text. Knowledge topic pool (see
    # ``data/knowledge_topics.json`` + ``KnowledgeTopicsCollector``)
    # replaces this feeding. Gated so it can be re-enabled for
    # experiments by flipping ``collection.google_trends_enabled`` in
    # experiments.yaml.
    if _xp_enabled("collection.google_trends_enabled", default=False):
        try:
            gt_cfg = (
                config.get("collection", {}).get("google_trends", {}) or {}
            )
            gt = GoogleTrendsCollector(
                max_results=gt_cfg.get("max_results", 30),
            )
            articles = gt.collect()
            collected["note"].extend(articles)
            logger.info("Google Trends: %d件収集", len(articles))
        except Exception as e:
            logger.error("Google Trends収集エラー: %s", e)
    else:
        logger.info(
            "Google Trends: DISABLED (knowledge-topics driven strategy)",
        )

    # Knowledge topics: CLAUDE.md の5 pillar (韓国美容 / 隠れた名店 /
    # コーヒー / 自分磨き / AI副業) を evergreen topic pool から供給。
    # noteは自己啓発/ナレッジの場であるという編集方針に沿う。
    try:
        from collectors.knowledge_topics_collector import (
            KnowledgeTopicsCollector,
        )
        kt = KnowledgeTopicsCollector()
        kt_articles = kt.collect()
        collected["note"].extend(kt_articles)
        logger.info("Knowledge topics: %d件収集", len(kt_articles))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Knowledge topics収集スキップ (%s) — pool未設定?", e,
        )

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
    """LLMバックエンドを初期化する。(claude or local)

    Uses the model configured for the ``writer`` task — falls back to
    ``gemma3:12b`` unless ``LLM_MODEL_WRITER`` env var overrides it.
    """
    local_llm = get_llm("writer")
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

    # Word count regen feedback — only fires when the article is
    # below the A-grade window (4000-5500). Targets re-tuned 2026-05-01
    # evening to match Gemma3 12B's realistic ceiling: aim for 4500
    # rather than the original 5500 push so the regen prompt stays
    # achievable in one retry.
    wc = metrics.get("word_count") or {}
    current_chars = wc.get("count", 0)
    if wc.get("grade") in ("B", "C") or current_chars < 4000:
        shortfall = max(4500 - current_chars, 600)
        weak.append(
            f"- 文字数が{current_chars}字しかない。**最低4500字、目標5000字**まで伸ばす"
            f"(現在より{shortfall}字以上追加)。以下のいずれかで各H2セクションを厚くする:\n"
            f"    ・各セクションに固有名詞つきの具体例を2つ以上\n"
            f"    ・引用ブロック(>)で一次情報を直接引く(最低3箇所)\n"
            f"    ・数値データ(再生回数/売上/割合)を本文に埋め込む\n"
            f"    ・読者への問いかけ→回答の往復で1段落追加\n"
            f"    ・H2セクションの数を4個 → 5個程度に増やす"
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
    # Sprint 3 (2026-05-11): pre-generation duplicate detection.
    # Surfaces past articles that semantic-match the new topic above
    # the threshold so the operator sees the warning in logs. Runs only
    # on the first attempt (regen-loop articles are by definition
    # not duplicates) and never blocks — logs only.
    if _regen_attempt == 0:
        kt = article.get("knowledge_topic") or {}
        promise = kt.get("promise", "") if isinstance(kt, dict) else ""
        _check_topic_duplication(
            title=article.get("title", ""),
            promise=promise,
        )

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
            # Fail-closed when Codex grounding is unavailable: original
            # purpose was to keep gourmet/spot articles from naming
            # made-up stores. But Codex is currently unreliable on this
            # box (Windows sandbox CreateProcessAsUserW errors), and
            # AI/tech note articles don't need store verification at
            # all. Allow opt-out via env var so the user can ship
            # AI notes during Codex outages.
            allow_no_brief = os.environ.get(
                "NOTE_ALLOW_NO_CODEX_BRIEF", ""
            ).strip().lower() in {"1", "true", "yes", "on"}
            if allow_no_brief:
                logger.warning(
                    "[note] Codex brief empty — proceeding anyway "
                    "(NOTE_ALLOW_NO_CODEX_BRIEF=1)"
                )
            else:
                logger.warning(
                    "[note] Codex research brief is empty — rejecting "
                    "article rather than generating ungrounded content. "
                    "Set NOTE_ALLOW_NO_CODEX_BRIEF=1 to bypass."
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
    learned_block = ""
    if platform == "note" and _xp_enabled("learn.learned_block"):
        # Sprint 4 (2026-05-11): when RAG_ENABLED is set, prefer
        # semantic retrieval over static stuffing — narrows the LLM's
        # attention to patterns relevant to *this* topic. Falls back
        # transparently to the static block when RAG returns empty.
        kt = article.get("knowledge_topic") or {}
        query_seed = " ".join(
            filter(None, [
                article.get("title", "")[:120],
                kt.get("promise", "") if isinstance(kt, dict) else "",
            ])
        )[:400]
        if query_seed:
            learned_block = _build_rag_learned_block(query_seed, platform)
        if not learned_block:
            learned_block = _load_learned_block()

    # Knowledge-topic injection — when the seed came from the evergreen
    # pool, pass the structured persona/pain/promise/outline to the LLM
    # so it writes to a real reader-pain brief instead of improvising
    # around a bare title. This is what replaces the news-driven Google
    # Trends flow (pivot 2026-04-23 after the 花澤香菜 / 令和ロマン
    # hallucination incidents).
    knowledge_block = ""
    kt = article.get("knowledge_topic")
    if kt and isinstance(kt, dict):
        outline = kt.get("outline", "")
        prohibited = kt.get("prohibited_angles") or []
        evidence_required = kt.get("evidence_required") or []
        # Render outline as explicit "## section name" lines so Gemma3
        # treats each slash-separated item as an independent H2 instead
        # of nesting them under a single big H2 (observed 2026-05-11:
        # all 5 AI×副業 articles failed heading_structure with only 1
        # H2). Empty splits and noise tokens are dropped.
        outline_sections = [
            s.strip() for s in outline.split("/") if s.strip()
        ]
        outline_block = (
            "\n".join(f"## {s}" for s in outline_sections)
            if outline_sections
            else outline
        )
        parts = [
            "\n\n【この記事の設計書 — 必ず従うこと】",
            f"ペルソナ: {kt.get('persona', '')}",
            f"読者の課題: {kt.get('pain', '')}",
            f"約束する価値: {kt.get('promise', '')}",
            "構成の骨子 — 以下の各 `##` 見出しを **独立した H2 セクション** "
            "として本文に含めること (H2 を 1 個にまとめず、必ずこの順序で複数の H2 を出力する):",
            outline_block,
        ]
        if evidence_required:
            parts.append(
                "必要な一次ソース: " + " / ".join(evidence_required),
            )
        if prohibited:
            parts.append(
                "書いてはいけない角度: " + " / ".join(prohibited),
            )
        parts.append(
            "骨子の各セクションは最低 500 字、全体 2800 字以上。"
            "根拠のない固有名詞/URL/ブランド名を創作してはいけない。"
            "参考リンクに placeholder (『ここに入力』『実際には〜URLを』) を残すと不合格。",
        )
        knowledge_block = "\n".join(parts) + "\n"

    # --- 生成 ---
    try:
        prompt = (
            template.format(**article)
            + structure_instruction
            + bracket_hint
            + research_block
            + learned_block
            + knowledge_block
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

    # --- LLM出力アーティファクトのsanitize（架空のURL等のplaceholder、
    #     空欄バレット連続を除去） — 客観/主観スコアより前。両プラットフォーム共通 ---
    from generators.content_sanitizer import sanitize as _sanitize_llm_output
    content, _stripped = _sanitize_llm_output(content)
    if _stripped:
        logger.info(
            "[%s] content sanitizer: %d artifact(s) removed",
            platform, len(_stripped),
        )

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
    # Scorer uses a separately-configured LLM (env: LLM_MODEL_SCORER) to
    # avoid writer→scorer self-grading bias when both run the same model.
    _scorer_llm = get_llm("scorer")
    eval_fn = (
        _scorer_llm.generate if use_local
        else lambda p: claude.send_prompt(p)
    )
    subj_evaluator = SubjectiveEvaluator()
    hallu_warnings = _retrieve_hallucination_warnings(content)
    subj_result = subj_evaluator.score(content, eval_fn, {
        "research_brief": article.get("content", ""),
        "hallucination_warnings": hallu_warnings,
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
        # Preview-generate the hashtag set the publish flow will emit
        # so tag_coverage_pct reflects what readers actually see. Old
        # path scanned the body for inline #tags, but note bodies
        # don't carry hashtags — stats were structurally stuck at 0%.
        try:
            _preview_hashtags = HashtagGenerator(max_tags=10).generate(
                title=article["title"],
                content=content,
                source=article.get("source", ""),
            )
        except Exception as _exc:  # noqa: BLE001
            logger.debug("hashtag preview failed: %s", _exc)
            _preview_hashtags = []
        adoption = _compute_learn_adoption(content, tags=_preview_hashtags)
        final["learn_adoption"] = adoption
        logger.info(
            "[%s] learn採用率: brackets=%s phrases=%d/%d tags=%.0f%% (preview-tags=%d)",
            platform,
            "✓" if adoption["bracket_present"] else "✗",
            adoption["phrase_hits"], adoption["phrase_total"],
            adoption["tag_coverage_pct"],
            len(_preview_hashtags),
        )

    # Record which A/B flags were active for this generation so later
    # analysis can compare score / view distributions across variants.
    # Lands on both the scores dict (so ArticleStore persists it) and
    # the return dict (for direct callers).
    _xp_record_variant(final, [
        "learn.learned_block",
        "learn.failure_patterns",
        "learn.track_adoption",
        "hashtag.blend_learned",
        "regen.thin_content_retry",
        "regen.char_count_feedback",
        "image.body_fallback_query",
        "publish.zenn_scrap_only",
    ])

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

        # note: Google Trends枠予約ロジックを廃止 (2026-04-23)。
        # noteのfeeding戦略が news → evergreen knowledge topics に移行
        # したため、Trends枠の保留は不要。残す場合はfallbackとして
        # experiments.yaml::collection.google_trends_enabled を True に。
        selection = candidates[:articles_per_week]
        if platform == "note" and _xp_enabled(
            "collection.google_trends_enabled", default=False,
        ):
            from collections import Counter
            recent_areas = _load_recent_note_areas()
            recent_counts = Counter(recent_areas)
            trends_candidates = [
                a for a in candidates if a.get("source") == "google_trends"
            ]

            def _area_rank(art: dict) -> tuple[int, float]:
                area = _area_of_article(art)
                return (
                    -recent_counts.get(area, 0),
                    float(art.get("trend_score", 0)),
                )

            trends_candidates.sort(key=_area_rank, reverse=True)
            top_trends = trends_candidates[0] if trends_candidates else None
            if top_trends and top_trends not in selection:
                if selection:
                    selection[-1] = top_trends
                else:
                    selection = [top_trends]
                picked_area = _area_of_article(top_trends) or "-"
                logger.info(
                    "[note] Google Trends枠(legacy): [%s] %s",
                    picked_area, top_trends.get("title", "")[:40],
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
                    # Knowledge-topic cooldown: record the topic id on
                    # the cooldown log so it's skipped until the
                    # ``cooldown_days`` window elapses. Gated on actual
                    # success so a rejected article still lets us
                    # retry the topic on a future run.
                    kt = article.get("knowledge_topic") or {}
                    kt_id = kt.get("id") if isinstance(kt, dict) else None
                    if kt_id:
                        try:
                            from collectors.knowledge_topics_collector import (
                                record_topic_used,
                            )
                            record_topic_used(kt_id)
                        except Exception:  # noqa: BLE001
                            pass
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
    # Narrow deny list to niche SNS (Bluesky/Threads/Mastodon) where
    # account verification is weak and fabricated posts dominate.
    # X/Instagram/Facebook allow post-URL verification so the article
    # body's forbidden_phrases guard catches hallucinations there
    # without publish-time over-blocking.
    _PUBLISH_DENY_PATTERNS = [
        _re.compile(r"氏の\s*(?:Bluesky|Threads|Mastodon)\s*投稿"),
        _re.compile(r"さんの\s*(?:Bluesky|Threads|Mastodon)\s*投稿"),
        _re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿が話題"),
        _re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿を徹底"),
        _re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿から徹底"),
        _re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿から読み解"),
        _re.compile(r"架空の\s*URL"),
        # 2026-05-07 一人飯記事で○○寿司/××焼鳥/□□ラーメン/△△バルが
        # 全店伏字で公開された実害事故。settings.yaml にも入っているが、
        # ここにハードコードして「外せない」状態にする (公開時の最終防衛線)。
        _re.compile(
            r"(?:〇〇|◯◯|○○|△△|××|□□|■■)"
            r"(?:寿司|寿し|鮨|焼鳥|やきとり|ラーメン|つけ麺|バル|バー|"
            r"ビストロ|食堂|酒場|割烹|蕎麦|そば|うどん|カレー|カフェ|"
            r"喫茶|ベーカリー|スイーツ|和菓子|洋菓子|焼肉|鉄板|串カツ|"
            r"串揚げ|天ぷら|うなぎ|もんじゃ|お好み焼|ピザ|フレンチ|"
            r"イタリアン|中華|韓国料理|タイ料理|居酒屋|ホルモン|"
            r"ジビエ|ステーキ|定食)",
        ),
        _re.compile(
            r"(?:〇〇|◯◯|○○|△△|××|□□|■■)"
            r"[一-龯ぁ-ゔァ-ヶー]{0,6}店(?![名称])",
        ),
        # 「（仮名）」 等の明示的フィクション開示。実在店記事の中身を偽る逃げ口上。
        _re.compile(r"（\s*(?:仮名|仮称|架空|フィクション)\s*）"),
        _re.compile(r"\(\s*(?:仮名|仮称|架空|フィクション)\s*\)"),
        # AI 開示 footer は読者への裏切り。2026-05-08 に「AI が構成」変種で
        # 11 件公開済記事が判明したのを受けて動詞群を拡充 (構成/編集/書き起こ も追加)。
        _re.compile(
            r"本記事は[^\n]{0,20}"
            r"(?:AI|ChatGPT|Claude|Gemini|GPT|生成AI|人工知能)"
            r"[^\n]{0,40}(?:生成|作成|執筆|書き起こ|構成|編集)",
        ),
        _re.compile(
            r"本記事の[^\n]{0,30}"
            r"(?:AI|ChatGPT|Claude|Gemini|GPT|生成AI|人工知能)"
            r"[^\n]{0,40}(?:生成|作成|執筆|書き起こ|構成|編集)",
        ),
        _re.compile(
            r"(?:AI|ChatGPT|Claude|Gemini|GPT)\s*(?:による|が)"
            r"\s*(?:自動)?(?:生成|作成|執筆|構成|編集)",
        ),
        _re.compile(
            r"AIによって(?:生成|作成|執筆|構成|編集|自動生成)された",
        ),
        _re.compile(
            r"本記事の[^\n]{0,20}(?:正確性|最新性|内容)"
            r"を保証(?:するもの|いたしません)",
        ),
        # 英語形式 (海外読者向け記事で混入した場合の保険)
        _re.compile(
            r"(?:Generated|Written|Created|Produced)\s+by\s+"
            r"(?:AI|ChatGPT|Claude|GPT|Gemini)",
            _re.IGNORECASE,
        ),
    ]

    # Codex Q2 (2026-04-23): the publish-time deny list above only
    # catches the Bluesky/架空URL patterns — it didn't see the new
    # forbidden_phrases (placeholder text, empty-URL bullets, 〇〇
    # placeholders) so today's 5 broken note articles slipped past.
    # Extend the deny check by also loading the scorer's
    # forbidden_phrases at publish time. Compiled once per pipeline
    # run for speed.
    _SETTINGS_FORBIDDEN: list[_re.Pattern[str]] = []
    try:
        _settings = config.get("evidence", {}) or {}
        for _raw in _settings.get("forbidden_phrases") or []:
            try:
                _SETTINGS_FORBIDDEN.append(_re.compile(
                    _raw, _re.MULTILINE | _re.DOTALL,
                ))
            except _re.error as _exc:
                logger.warning(
                    "publish-deny: 不正な正規表現をスキップ: %r (%s)",
                    _raw, _exc,
                )
    except Exception as _exc:  # noqa: BLE001
        logger.warning("publish-deny: settings 読込失敗: %s", _exc)
    _ALL_PUBLISH_DENY = _PUBLISH_DENY_PATTERNS + _SETTINGS_FORBIDDEN

    def _deny_reason(txt: str) -> str | None:
        for pat in _ALL_PUBLISH_DENY:
            m = pat.search(txt)
            if m:
                return m.group(0)[:60]
        return None

    # Hybrid Zenn batch state: once we observe an article-publish
    # land on a 404 (Zenn's silent ~12-cap drop), every remaining
    # zenn article in the same publish run goes straight to scrap
    # without paying the 25-second 404-wait again.
    _zenn_cap_exhausted = False

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
        # the extracted JP title, the head OR the tail of the body
        # matches any of the hallucination/placeholder patterns. The
        # tail is critical because 参考リンク placeholders and
        # empty-URL bullets (はしか/サンケイビル 2026-04-23 events)
        # live at the bottom of the article. Flip the sheet row to ❌
        # 却下 so the operator sees why it was blocked.
        _deny_hit = (
            _deny_reason(article_data.get("title", ""))
            or _deny_reason(title)
            or _deny_reason(content[:2500])
            or _deny_reason(content[-2500:])
        )
        # 2026-04-28: align publish-time deny with the objective_scorer
        # note-relaxation. For note articles, the empty-bullet "Tool: "
        # placeholder pattern is a structural artifact (LLM listing
        # tools without URLs), not a fact-hallucination. The scorer
        # already lets these through, so the publish deny should too —
        # otherwise we register the article in Sheets, mark it
        # 投稿済み-eligible, then silently flip to ❌却下 here. The
        # *real* fact-precision deny patterns (Bluesky/Threads,
        # トレンド入り、架空, 〇〇, etc.) still block on note.
        _structural_template_markers = (
            "公式サイト", "公式ドキュメント", "ここに入力",
            "URLは記載しません", "実際には", "サンプルリポジトリ",
        )
        _danger_markers = (
            "Bluesky", "Threads", "Mastodon",
            "トレンド入り", "話題を呼んで", "議論を呼んで",
            "架空", "Dr. X", "〇〇", "◯◯", "○○", "△△", "××", "□□", "■■",
            # 2026-05-08 拡充: 伏字+業態語(自動検出が非常に重要), 仮名/仮称, AI 開示
            "寿司", "焼鳥", "ラーメン", "バル", "焼肉", "居酒屋",
            "仮名", "仮称", "フィクション",
            "AIが", "AIによって", "AIで自動生成", "Generated by",
        )
        # 2026-05-08 BMW 却下事故対応: scorer は note の empty-bullet
        # tech list (Tool: \n Tool: \n) を相対緩和して通すが、publish-deny
        # 側は marker 一覧との文字列一致しか見ておらず "BMW Group: " のような
        # 同じ構造でも落としていた。scorer と同じ regex を使って整合させる。
        _empty_bullet_re = re.compile(
            r"(?:\*|-)\s+[^*:\n]{2,60}:\s*\n.*(?:\*|-)\s+[^*:\n]{2,60}:\s*\n",
            re.DOTALL,
        )
        _is_empty_bullet_template = bool(
            _deny_hit and _empty_bullet_re.search(_deny_hit)
        )
        if (
            _deny_hit
            and platform == "note"
            and (
                any(m in _deny_hit for m in _structural_template_markers)
                or _is_empty_bullet_template
            )
            and not any(d in _deny_hit for d in _danger_markers)
        ):
            logger.info(
                "[note] publish deny hit was structural template "
                "(%s) — passing through (parity with objective_scorer)",
                _deny_hit[:60],
            )
            _deny_hit = None
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
                # When publish.zenn_scrap_only is on, route everything
                # to Zenn Scraps regardless of score. Used while the
                # Zenn article-publish rate limit / visibility issue
                # from 2026-04-20 (10-article cap showing newer posts
                # as 404) is not fully resolved — scraps have no such
                # cap and still surface in the author's feed.
                if _xp_enabled("publish.zenn_scrap_only", default=False):
                    logger.info(
                        "[zenn] scrap_only=on → score=%.1f でスクラップ投稿",
                        numeric_score,
                    )
                    url = _save_scrap_draft(article_id, title, content, stored)
                elif _zenn_cap_exhausted:
                    # An earlier article in this batch already 404'd
                    # → Zenn's cap is full for this account. Don't
                    # waste another git push that will silently drop;
                    # publish straight to a scrap so it surfaces.
                    logger.info(
                        "[zenn] cap exhausted in this batch → スクラップ投稿"
                    )
                    url = _save_scrap_draft(article_id, title, content, stored)
                elif numeric_score >= ZENN_ARTICLE_THRESHOLD:
                    logger.info(
                        "[zenn] score=%.1f >= %.1f → 記事投稿",
                        numeric_score, ZENN_ARTICLE_THRESHOLD,
                    )
                    url = _publish_zenn(article_id, title, content, stored)
                    # Two failure modes both fall back to scrap:
                    #   (a) _publish_zenn returned None — git push or
                    #       commit failed (e.g. nothing-to-commit when
                    #       a previous run already pushed the .md).
                    #   (b) URL is set but Zenn returns 404 — the
                    #       known 12-article-cap silent drop.
                    # In both cases the user's intent ("publish this
                    # zenn article") is best served by re-publishing
                    # as a scrap, which has no cap. Set the batch
                    # flag so subsequent zenn entries skip the article
                    # attempt entirely.
                    if url is None:
                        logger.warning(
                            "[zenn] article publish returned None — "
                            "falling back to scrap + flagging batch"
                        )
                        _zenn_cap_exhausted = True
                        url = _save_scrap_draft(
                            article_id, title, content, stored,
                        )
                    elif _is_zenn_article_404(url):
                        logger.warning(
                            "[zenn] article 404 detected (cap likely hit) — "
                            "falling back to scrap for this article + "
                            "switching rest of batch to scrap mode"
                        )
                        _zenn_cap_exhausted = True
                        url = _save_scrap_draft(
                            article_id, title, content, stored,
                        )
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
                # Persist the published URL back onto the stored
                # article so `scripts/analyze_performance.py` can
                # join performance rows (which know the noteUrl) to
                # the scores dict without relying on 39% fuzzy title
                # matching (Codex review 2026-04-23).
                # Cross-check note: log at WARNING (not debug) so a
                # silent persist failure can't quietly break the
                # quality loop's exact-join improvement.
                try:
                    store = ArticleStore()
                    stored = store.load(article_id) or {}
                    stored["published_url"] = url
                    stored["published_at"] = datetime.now().isoformat()
                    store.save(article_id, stored)
                except Exception as _exc:  # noqa: BLE001
                    logger.warning(
                        "published_url 永続化失敗 (id=%s url=%s): %s",
                        article_id, url, _exc,
                    )
                logger.info("[%s] 投稿完了: %s", platform, title[:40])

        except Exception as e:
            logger.error("[%s] 投稿エラー: %s — %s", platform, title[:30], e)
            slack.notify_error(str(e), f"{platform}: {title[:30]}")
            gmail.notify_error(str(e), f"{platform}: {title[:30]}")

    return results


def _is_zenn_article_404(url: str, indexing_wait_sec: int = 25) -> bool:
    """Verify a freshly-pushed Zenn article URL actually surfaces.

    The known 2026-04-20+ bug: Zenn's GitHub integration silently
    drops articles once the author's published-article count exceeds
    a hidden cap (~12 at last measurement). The git push succeeds,
    the file lands in zenn-content with ``published: true``, but the
    URL stays 404 forever. The only way to detect it is to hit the
    URL after Zenn's normal indexing window (~20-30s) and see what
    we get. Returns True on confirmed 404, False on 200 or any
    transient error (caller treats False as success).
    """
    if not url or "/articles/" not in url:
        return False
    # ``requests`` is imported lazily as ``_requests`` elsewhere in
    # main.py for SSRF-allowlisting reasons; reuse the same alias.
    import requests as _r
    try:
        time.sleep(indexing_wait_sec)
        resp = _r.head(url, timeout=15, allow_redirects=True)
        is_404 = resp.status_code == 404
        logger.info(
            "[zenn] URL check %s → HTTP %d", url, resp.status_code,
        )
        return is_404
    except _r.RequestException as exc:
        logger.warning("[zenn] URL check failed (%s) — assuming OK", exc)
        return False


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
        zenn_user = os.getenv("ZENN_USERNAME", "zenn-user")
        return f"https://zenn.dev/{zenn_user}/articles/{zenn_slug}"
    return None


def _fetch_topic_cover(title: str, content: str = "") -> Path | None:
    """Download an Unsplash photo themed to *title* for the eyecatch.

    Falls through to ``None`` so the caller can decide whether to
    fall back to the PIL KENTO mascot (NoteCoverGenerator) or skip
    the cover entirely.

    Accepts optional *content* so the genre-aware mood modifier
    (``_IMAGE_MOOD_RULES``) fires on cover images too. Cover CTR is
    the single biggest lever on list-page click-through on note, so
    picking a cosmetics-looking shot for a cosmetics post — not a
    generic "lifestyle" shot — is worth the extra scan.
    """
    try:
        from generators.image_sourcer import ImageSourcer
        sourcer = ImageSourcer()
        query = _extract_image_query(title, content)
        # Over-fetch + relevance filter so the cover doesn't end up
        # being the kind of mismatched stock photo that triggered the
        # 2026-04-30 tombstone/sewing-machine/cherry-blossom incident.
        # find_images returns Unsplash's keyword guess and we have to
        # reject obvious red-flag alts before the image becomes the
        # face of the article (cover CTR matters more than inline).
        results = sourcer.find_images(query, count=8)
        results = [
            r for r in results
            if r.get("url")
            and r.get("platform") != "Placeholder"
            and _alt_is_relevant(r.get("alt_text", ""), title, content)
            and _alt_matches_query_subject(r.get("alt_text", ""), query)
        ]
        if not results:
            logger.info(
                "[cover] no Unsplash result passed relevance filter for %r",
                query,
            )
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
        # Log the cover's image query + slug so the thumbnail-CTR
        # tracker can later correlate "which image queries drove the
        # most views". Silent on failure; logging is best-effort.
        try:
            _log_thumbnail_choice(title=title, query=query, path=str(out))
        except Exception as _exc:
            logger.debug("thumbnail log failed: %s", _exc)
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

        # Image cascade (2026-04-28): ChatGPT Ghibli-style first
        # (default ON), then existing Unsplash flow. The cascade is
        # owned by chatgpt_batch_helper which short-circuits when
        # Brave is running or USE_CHATGPT_IMAGES=0 is set, so the old
        # behaviour stays the fallback path — degradation only when
        # ChatGPT is opted out, never silently changes.
        cover_path: Path | str | None = None
        try:
            from generators.chatgpt_batch_helper import (
                chatgpt_image_batch,
                is_chatgpt_image_gen_enabled,
            )
            if is_chatgpt_image_gen_enabled():
                cgpt_cover, cgpt_inline = chatgpt_image_batch(
                    title=title,
                    content=content,
                    inline_count=4,
                    slug_hint=re.sub(r"[^a-zA-Z0-9_-]", "_", title)[:40],
                    genre_hint=source or "general tech / lifestyle",
                )
                if cgpt_cover:
                    cover_path = cgpt_cover
                # Use ChatGPT inline images when produced; if partial,
                # we keep what we got and let the body-harvested
                # inline_images stay as the rest. Caps at 4 by note's
                # editor-paste rules.
                if cgpt_inline:
                    chatgpt_inline_strs = [
                        str(p.resolve()) for p in cgpt_inline
                    ]
                    if not inline_images:
                        inline_images = chatgpt_inline_strs[:4]
                    else:
                        # Prepend ChatGPT images so they render first.
                        inline_images = (
                            chatgpt_inline_strs + inline_images
                        )[:4]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[note] ChatGPT image batch failed (%s); "
                "falling back to Unsplash cover.", exc,
            )

        # Existing Unsplash fallback for the cover.
        if cover_path is None:
            cover_path = _fetch_topic_cover(title, content)

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

        # Run subjective scoring (separate scorer model — see LLM_MODEL_SCORER)
        eval_fn = get_llm("scorer").generate
        subj_evaluator = SubjectiveEvaluator()
        hallu_warnings = _retrieve_hallucination_warnings(content)
        subj_result = subj_evaluator.score(content, eval_fn, {
            "research_brief": "",
            "hallucination_warnings": hallu_warnings,
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

        # --- Self-improving quality loop (added 2026-04-23) ---
        # Pipeline stage (3/3): scrape own-article performance →
        # cross-join with experiment_variant / learn_adoption → emit
        # quality_successes.md which _load_learned_block will inject
        # into the next generation's note prompt. Failures here are
        # swallowed — the core learn report was already written above.
        import subprocess as _sp
        for _script in (
            "scripts/scrape_note_performance.py",
            "scripts/analyze_performance.py",
        ):
            try:
                _rc = _sp.call(
                    [sys.executable, "-X", "utf8", _script],
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                if _rc != 0:
                    logger.warning(
                        "quality loop step %s exited rc=%d", _script, _rc,
                    )
            except Exception as _exc:  # noqa: BLE001
                logger.warning(
                    "quality loop step %s failed: %s", _script, _exc,
                )

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
