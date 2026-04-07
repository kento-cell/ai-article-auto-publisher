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
import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from collectors.arxiv_collector import ArxivCollector
from collectors.reddit_collector import RedditCollector
from collectors.rss_collector import RssCollector
from collectors.trend_detector import TrendDetector
from generators.claude_automator import ClaudeAutomator
from generators.local_llm import LocalLLM
from generators.diagram_generator import DiagramGenerator
from generators.evidence_manager import EvidenceManager
from generators.objective_scorer import ObjectiveScorer
from generators.subjective_evaluator import SubjectiveEvaluator
from generators.score_aggregator import ScoreAggregator
from publishers.zenn_publisher import ZennPublisher
from publishers.note_publisher import NotePublisher
from publishers.slack_notifier import SlackNotifier
from publishers.gmail_notifier import GmailNotifier
from utils.sheets_manager import SheetsManager
from utils.token_manager import TokenManager, estimate_tokens
from utils.feedback_recorder import FeedbackRecorder
from utils.logger import setup_logger

load_dotenv()
logger = setup_logger(__name__)


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
        return yaml.safe_load(f)


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

    try:
        claude = ClaudeAutomator()
        return claude, local_llm, False
    except Exception as e:
        logger.warning("Claude.ai接続失敗: %s。ローカルLLMへ。", e)
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
) -> dict | None:
    """1記事を生成し、2層スコアリングを行う。

    Returns:
        スコアリング済み記事dict、またはNone（生成失敗/却下時）。
    """
    # --- 生成 ---
    try:
        prompt = template.format(**article)
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

    # --- 図表処理 ---
    diagram_gen = DiagramGenerator()
    content = diagram_gen.embed_diagrams(content, "docs/images")

    # --- 客観スコア ---
    evidence_mgr = EvidenceManager()
    forbidden = config.get("evidence", {}).get("forbidden_phrases", [])
    sources = article.get("sources", [])

    obj_scorer = ObjectiveScorer()
    obj_result = obj_scorer.score(content, {
        "sources": sources,
        "forbidden_phrases": forbidden,
    })

    if not obj_result["objective_pass"]:
        logger.info(
            "[%s] 客観スコア不合格: %s — %s",
            platform, article["title"][:30], obj_result["blocking_issues"]
        )
        return None

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
    slug = f"{platform}-{article.get('title', 'untitled')[:20]}"
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
        return None

    logger.info(
        "[%s] 生成完了: %s (総合: %s, 証拠Lv: %s)",
        platform,
        article["title"][:30],
        final["overall_grade"],
        final["evidence_level"],
    )

    return {
        "title": article["title"],
        "content": content,
        "source": article,
        "platform": platform,
        "slug": slug,
        "scores": final,
        "generated_at": datetime.now().isoformat(),
    }


def generate_and_score(
    ranked: dict,
    config: dict,
    prompts: dict,
    token_manager: TokenManager,
) -> list[dict]:
    """記事を生成し、2層スコアリングで評価する。

    Returns:
        スコアリング合格（A/B）の記事リスト。Cは含まれない。
    """
    logger.info("=== Phase 2: 生成 + スコアリング ===")
    claude, local_llm, use_local = _init_llm(token_manager)
    if local_llm is None and claude is None:
        return []

    approved = []

    for platform in ["zenn", "note"]:
        template = prompts.get(f"{platform}_article_prompt", "")
        articles_per_week = config.get("generation", {}).get(
            platform, {}
        ).get("articles_per_week", 1)

        for article in ranked.get(platform, [])[:articles_per_week]:
            try:
                result = _generate_single_article(
                    article, platform, template,
                    claude, local_llm, use_local,
                    token_manager, config,
                )
                if result:
                    approved.append(result)
            except Exception as e:
                logger.error(
                    "[%s] 生成エラー (%s): %s",
                    platform, article.get("title", "?")[:30], e
                )

    if claude:
        claude.close()

    return approved


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

        try:
            if platform == "zenn":
                url = _publish_zenn(article_id, title)
            elif platform == "note":
                url = _publish_note(title, config)
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


def _publish_zenn(slug: str, title: str) -> str | None:
    """Zenn記事を投稿する。"""
    zenn_repo = os.getenv("ZENN_REPO_PATH")
    if not zenn_repo:
        logger.warning("ZENN_REPO_PATH未設定。Zenn投稿スキップ。")
        return None
    publisher = ZennPublisher(zenn_repo)
    # slug に対応するファイルが既にある前提（generate時にcreate_article済み）
    success = publisher.publish(slug)
    return f"https://zenn.dev/articles/{slug}" if success else None


def _publish_note(title: str, config: dict) -> str | None:
    """note記事を投稿する。"""
    note_pub = None
    try:
        note_pub = NotePublisher()
        tags = ["AI", "テクノロジー", "トレンド"]
        url = note_pub.publish_article(
            title=title,
            content="",  # TODO: コンテンツの保存/取得の仕組みが必要
            tags=tags,
            price=0,
        )
        return url
    except Exception as e:
        logger.error("note投稿失敗: %s", e)
        return None
    finally:
        if note_pub:
            note_pub.close()


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
        approved = generate_and_score(ranked, config, prompts, token_manager)
        logger.info("スコアリング合格: %d件", len(approved))

        register_for_approval(approved, sheets, gmail)

        # 日次サマリー
        stats = {
            "articles_generated": len(approved),
            "articles_published": 0,
            "platforms": {"Zenn": 0, "note": 0},
            "avg_quality_score": 0.0,
            "errors": 0,
        }
        slack.notify_daily_summary(stats)
        gmail.notify_daily_summary(stats)

    elif mode == "publish":
        # Sheetsから承認済み記事を取得して投稿
        results = publish_approved(sheets, config, slack, gmail, feedback)
        pub_total = sum(len(v) for v in results.values())
        logger.info("投稿完了: %d件", pub_total)

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
        "--setup-sheets", action="store_true",
        help="Sheetsのフォーマット設定（ドロップダウン、条件付き書式等）",
    )
    args = parser.parse_args()

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
        approved = generate_and_score(
            ranked, config, prompts, token_manager
        )
        print(f"\n=== スコアリング合格: {len(approved)}件 ===")
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

    # --- publish ---
    if args.publish:
        run_pipeline(config, prompts, mode="publish")
        return

    # --- generate (default) ---
    run_pipeline(config, prompts, mode="generate")


if __name__ == "__main__":
    main()
