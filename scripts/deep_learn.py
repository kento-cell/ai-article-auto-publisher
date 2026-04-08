"""Deep learning run: scrape many categories and accumulate knowledge.

Runs until deadline time, then exits. Safe to run repeatedly.
"""

from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from scrapers.note_scraper import NoteScraper
from analyzers.pattern_extractor import PatternExtractor
from learners.prompt_updater import PromptUpdater


# Expanded category list - diverse topics for broader learning
CATEGORIES = [
    # Money / Business
    "business", "money", "副業", "投資", "マネタイズ", "稼ぐ",
    # Tech / AI
    "tech", "ai", "ChatGPT", "Claude", "プログラミング", "LLM", "自動化",
    # Lifestyle
    "lifestyle", "健康", "ダイエット", "美容", "恋愛", "結婚",
    # Creative
    "クリエイター", "イラスト", "小説", "漫画", "写真",
    # Learning
    "勉強", "英語", "資格", "読書", "教育",
    # Culture
    "グルメ", "旅行", "カフェ", "料理", "ファッション",
    # Career
    "転職", "キャリア", "フリーランス", "リモートワーク", "起業",
]


def main() -> None:
    deadline = datetime.now().replace(hour=23, minute=55, second=0, microsecond=0)
    print(f"[start] learning until {deadline.isoformat()}")

    scraper = NoteScraper()
    extractor = PatternExtractor()
    updater = PromptUpdater()

    # Accumulate articles across all categories
    all_articles = []
    cumulative_log = _ROOT / "docs" / "knowledge" / "note-trends" / "cumulative.json"
    if cumulative_log.exists():
        try:
            all_articles = json.loads(cumulative_log.read_text(encoding="utf-8"))
            print(f"[resume] loaded {len(all_articles)} existing articles")
        except Exception:
            pass

    seen_urls = {a.get("url") for a in all_articles if a.get("url")}

    category_idx = 0
    while datetime.now() < deadline and category_idx < len(CATEGORIES):
        category = CATEGORIES[category_idx]
        print(f"[fetch] {category}...")
        try:
            articles = scraper.fetch_popular_articles(category, limit=30)
            new_count = 0
            for a in articles:
                if a.get("url") and a["url"] not in seen_urls:
                    all_articles.append(a)
                    seen_urls.add(a["url"])
                    new_count += 1
            print(f"  +{new_count} new (total {len(all_articles)})")
        except Exception as e:
            print(f"  error: {e}")
        category_idx += 1
        time.sleep(2)

        # Periodically save progress
        if category_idx % 5 == 0:
            cumulative_log.parent.mkdir(parents=True, exist_ok=True)
            cumulative_log.write_text(
                json.dumps(all_articles, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  [saved checkpoint: {len(all_articles)} articles]")

    # Final save
    cumulative_log.parent.mkdir(parents=True, exist_ok=True)
    cumulative_log.write_text(
        json.dumps(all_articles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Analyze cumulative data
    print(f"\n[analyze] {len(all_articles)} total articles")
    patterns = extractor.extract_winning_patterns(all_articles)
    kb_path = updater.update_knowledge_base(patterns)
    sg_path = updater.suggest_prompt_improvements(patterns)
    print(f"  knowledge: {kb_path}")
    print(f"  suggestions: {sg_path}")
    print(f"[done] {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
