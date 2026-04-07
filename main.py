"""
AI記事自動生成・投稿システム メインスクリプト

Zenn（技術記事）とnote（一般向け記事）に自動で記事を生成・投稿する。
収集 → 評価 → 生成 → 品質チェック → 投稿 → 通知 のパイプラインを実行。
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from collectors.arxiv_collector import ArxivCollector
from collectors.reddit_collector import RedditCollector
from collectors.trend_detector import TrendDetector
from generators.claude_automator import ClaudeAutomator
from generators.local_llm import LocalLLM
from generators.diagram_generator import DiagramGenerator
from generators.evidence_manager import EvidenceManager
from generators.quality_evaluator import QualityEvaluator
from publishers.zenn_publisher import ZennPublisher
from publishers.note_publisher import NotePublisher
from publishers.slack_notifier import SlackNotifier
from utils.sheets_manager import SheetsManager
from utils.token_manager import TokenManager, estimate_tokens
from utils.logger import setup_logger

load_dotenv()
logger = setup_logger(__name__)


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
            "%s not found. Using default configuration. "
            "Copy %s.example to %s for customization.",
            config_path, config_path, config_path
        )
        return _default_config()

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prompts(prompts_path: str = "config/prompts.yaml") -> dict:
    """プロンプトテンプレートを読み込む。"""
    with open(prompts_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect_articles(config: dict) -> dict:
    """各ソースから記事を収集する。"""
    logger.info("=== 記事収集フェーズ開始 ===")
    collected = {"zenn": [], "note": []}

    # Zenn向け: arXiv
    try:
        arxiv = ArxivCollector(
            max_results=config.get("collection", {}).get("zenn", {}).get("max_articles", 10)
        )
        articles = arxiv.collect()
        collected["zenn"].extend(articles)
        logger.info("arXiv: %d件収集", len(articles))
    except Exception as e:
        logger.error("arXiv収集エラー: %s", e)

    # note向け: Reddit
    try:
        reddit = RedditCollector(
            max_results=config.get("collection", {}).get("note", {}).get("max_articles", 20)
        )
        articles = reddit.collect()
        collected["note"].extend(articles)
        logger.info("Reddit: %d件収集", len(articles))
    except Exception as e:
        logger.error("Reddit収集エラー: %s", e)

    return collected


def rank_articles(collected: dict) -> dict:
    """トレンドスコアで記事をランク付けする。"""
    logger.info("=== トレンドスコア計算フェーズ ===")
    detector = TrendDetector()
    ranked = {}

    for platform, articles in collected.items():
        ranked[platform] = detector.rank_articles(articles)
        if ranked[platform]:
            top = ranked[platform][0]
            logger.info(
                "%s トップ記事: %s (スコア: %.1f)",
                platform, top["title"][:40], top.get("trend_score", 0)
            )

    return ranked


def generate_articles(
    ranked: dict,
    config: dict,
    prompts: dict,
    token_manager: TokenManager
) -> dict:
    """ランク付けされた記事からコンテンツを生成する。"""
    logger.info("=== 記事生成フェーズ開始 ===")
    generated = {"zenn": [], "note": []}

    # LLM初期化
    claude = None
    local_llm = LocalLLM()
    use_local = not token_manager.is_within_budget()

    if use_local:
        logger.warning("トークン予算超過。ローカルLLMにフォールバック。")
        if not local_llm.is_available():
            logger.error("ローカルLLMも利用不可。生成をスキップ。")
            return generated
    else:
        try:
            claude = ClaudeAutomator()
        except Exception as e:
            logger.warning("Claude.ai接続失敗: %s。ローカルLLMにフォールバック。", e)
            use_local = True

    evidence_mgr = EvidenceManager()
    evaluator = QualityEvaluator()
    diagram_gen = DiagramGenerator()

    for platform in ["zenn", "note"]:
        prompt_key = f"{platform}_article_prompt"
        template = prompts.get(prompt_key, "")
        articles_per_week = config.get("generation", {}).get(platform, {}).get("articles_per_week", 2)
        min_score = config.get("generation", {}).get(platform, {}).get("min_quality_score", 45)

        for article in ranked.get(platform, [])[:articles_per_week]:
            try:
                # プロンプト生成
                prompt = template.format(**article)

                # 記事生成
                if use_local:
                    content = local_llm.generate(prompt)
                    token_manager.record_usage(estimate_tokens(prompt) + estimate_tokens(content))
                else:
                    content = claude.generate_article(template, article)
                    token_manager.record_usage(estimate_tokens(prompt) + estimate_tokens(content))

                # エビデンス検証
                forbidden = config.get("evidence", {}).get(
                    "forbidden_phrases", []
                )
                violations = evidence_mgr.check_forbidden_phrases(
                    content, forbidden
                )
                if violations:
                    logger.warning(
                        "禁止フレーズ検出: %s。記事スキップ。", violations
                    )
                    continue

                citation_result = evidence_mgr.validate_citations(content)
                if not citation_result["is_valid"]:
                    content = evidence_mgr.add_access_date(content)

                # 図表処理
                content = diagram_gen.embed_diagrams(content, "docs/images")

                # 品質評価
                eval_fn = (
                    local_llm.generate if use_local
                    else lambda p: claude.send_prompt(p)
                )
                scores = evaluator.evaluate(content, eval_fn)

                if evaluator.meets_threshold(scores, min_score):
                    generated[platform].append({
                        "title": article["title"],
                        "content": content,
                        "source": article,
                        "scores": scores,
                        "generated_at": datetime.now().isoformat(),
                    })
                    logger.info(
                        "[%s] 生成完了: %s (スコア: %d)",
                        platform, article["title"][:30],
                        scores.get("total", 0)
                    )
                else:
                    logger.info(
                        "[%s] 品質基準未達: %s (スコア: %d < %d)",
                        platform, article["title"][:30],
                        scores.get("total", 0), min_score
                    )

            except Exception as e:
                logger.error(
                    "[%s] 生成エラー (%s): %s",
                    platform, article.get("title", "?")[:30], e
                )

    # Claude cleanup
    if claude:
        claude.close()

    return generated


def publish_articles(
    generated: dict,
    config: dict,
    sheets: SheetsManager,
    notifier: SlackNotifier
) -> dict:
    """生成された記事を各プラットフォームに投稿する。"""
    logger.info("=== 投稿フェーズ開始 ===")
    results = {"zenn": [], "note": []}

    # Zenn投稿
    zenn_repo = os.getenv("ZENN_REPO_PATH")
    if zenn_repo and generated.get("zenn"):
        publisher = ZennPublisher(zenn_repo)
        for article in generated["zenn"]:
            try:
                topics = ["AI", "機械学習", "テクノロジー"]
                slug = publisher.create_article(
                    title=article["title"],
                    content=article["content"],
                    topics=topics,
                )
                success = publisher.publish(slug)
                if success:
                    results["zenn"].append(article["title"])
                    sheets.add_article({
                        "title": article["title"],
                        "platform": "zenn",
                        "status": "published",
                        "score": article["scores"].get("total", 0),
                        "published_date": datetime.now().isoformat(),
                    })
                    notifier.notify_published(
                        "Zenn", article["title"], f"https://zenn.dev"
                    )
                    logger.info("Zenn投稿完了: %s", article["title"][:40])
            except Exception as e:
                logger.error("Zenn投稿エラー: %s", e)
                notifier.notify_error(str(e), f"Zenn: {article['title'][:30]}")

    # note投稿
    if generated.get("note"):
        note_pub = None
        try:
            note_pub = NotePublisher()
            pricing_config = config.get("pricing", {})

            for article in generated["note"]:
                try:
                    score = article["scores"].get("total", 0)
                    word_count = len(article["content"])
                    price = note_pub.determine_price(score, word_count)

                    tags = ["AI", "テクノロジー", "トレンド"]
                    url = note_pub.publish_article(
                        title=article["title"],
                        content=article["content"],
                        tags=tags,
                        price=price,
                    )
                    if url:
                        results["note"].append(article["title"])
                        sheets.add_article({
                            "title": article["title"],
                            "platform": "note",
                            "status": "published",
                            "score": score,
                            "price": price,
                            "published_date": datetime.now().isoformat(),
                        })
                        notifier.notify_published(
                            "note", article["title"], url
                        )
                        logger.info(
                            "note投稿完了: %s (¥%d)",
                            article["title"][:40], price
                        )
                except Exception as e:
                    logger.error("note投稿エラー: %s", e)
                    notifier.notify_error(
                        str(e), f"note: {article['title'][:30]}"
                    )
        finally:
            if note_pub:
                note_pub.close()

    return results


def run_pipeline(config: dict, prompts: dict):
    """メインパイプラインを実行する。"""
    logger.info("========================================")
    logger.info("AI記事自動生成システム 実行開始")
    logger.info("日時: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("========================================")

    token_manager = TokenManager()
    notifier = SlackNotifier()
    sheets = SheetsManager()

    # 1. 収集
    collected = collect_articles(config)
    total = sum(len(v) for v in collected.values())
    logger.info("収集完了: 合計%d件", total)

    if total == 0:
        logger.warning("収集記事0件。パイプライン終了。")
        return

    # 2. ランク付け
    ranked = rank_articles(collected)

    # 3. 生成
    generated = generate_articles(ranked, config, prompts, token_manager)
    gen_total = sum(len(v) for v in generated.values())
    logger.info("生成完了: 合計%d件", gen_total)

    # 4. 投稿
    results = publish_articles(generated, config, sheets, notifier)

    # 5. サマリー通知
    stats = {
        "articles_generated": gen_total,
        "articles_published": len(results.get("zenn", [])) + len(results.get("note", [])),
        "platforms": {
            "Zenn": len(results.get("zenn", [])),
            "note": len(results.get("note", [])),
        },
        "avg_quality_score": 0.0,  # TODO: calculate from generated articles
        "errors": 0,  # TODO: track error count
    }
    notifier.notify_daily_summary(stats)

    logger.info("========================================")
    logger.info("パイプライン完了")
    logger.info(
        "投稿: Zenn=%d, note=%d",
        stats["platforms"]["Zenn"], stats["platforms"]["note"]
    )
    logger.info("========================================")


def main():
    """エントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="AI記事自動生成・投稿システム"
    )
    parser.add_argument(
        "--config", default="config/settings.yaml",
        help="設定ファイルパス (default: config/settings.yaml)"
    )
    parser.add_argument(
        "--collect-only", action="store_true",
        help="収集のみ実行（生成・投稿しない）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="投稿せずに生成まで実行"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    prompts = load_prompts()

    if args.collect_only:
        collected = collect_articles(config)
        ranked = rank_articles(collected)
        for platform, articles in ranked.items():
            print(f"\n=== {platform} ===")
            for i, a in enumerate(articles[:5], 1):
                print(f"{i}. [{a.get('trend_score', 0):.1f}] {a['title']}")
        return

    if args.dry_run:
        logger.info("ドライラン: 投稿はスキップされます")
        collected = collect_articles(config)
        ranked = rank_articles(collected)
        token_manager = TokenManager()
        generated = generate_articles(ranked, config, prompts, token_manager)
        for platform, articles in generated.items():
            print(f"\n=== {platform}: {len(articles)}件生成 ===")
            for a in articles:
                print(f"  - {a['title']} (スコア: {a['scores'].get('total', 0)})")
        return

    run_pipeline(config, prompts)


if __name__ == "__main__":
    main()
