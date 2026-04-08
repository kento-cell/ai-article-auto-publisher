"""Phase 2: Fetch detail pages + expand categories until deadline."""

from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from scrapers.note_scraper import NoteScraper
from analyzers.pattern_extractor import PatternExtractor
from learners.prompt_updater import PromptUpdater


EXTRA_CATEGORIES = [
    # Finance / crypto
    "株", "NISA", "FIRE", "仮想通貨", "Bitcoin",
    # Media / entertainment
    "映画", "音楽", "YouTube", "TikTok", "Instagram",
    # Wellness
    "メンタル", "睡眠", "瞑想", "ヨガ", "筋トレ",
    # Parenting
    "育児", "子育て", "子ども",
    # Career niches
    "エンジニア", "デザイナー", "ライター", "マーケティング", "営業",
    # Trending
    "節約", "ミニマリスト", "断捨離", "韓国", "中国",
    # Specific AI
    "Gemini", "画像生成", "AIイラスト", "プロンプト",
]


def main() -> None:
    deadline = datetime.now().replace(hour=23, minute=55, second=0, microsecond=0)
    print(f"[phase2 start] until {deadline.isoformat()}")

    scraper = NoteScraper()
    extractor = PatternExtractor()
    updater = PromptUpdater()

    cumulative_log = _ROOT / "docs" / "knowledge" / "note-trends" / "cumulative.json"
    all_articles = []
    if cumulative_log.exists():
        try:
            all_articles = json.loads(cumulative_log.read_text(encoding="utf-8"))
            print(f"[loaded] {len(all_articles)} existing articles")
        except Exception:
            pass

    seen_urls = {a.get("url") for a in all_articles if a.get("url")}

    # Phase A: fetch extra categories
    print("\n[phase A] expanding categories")
    for category in EXTRA_CATEGORIES:
        if datetime.now() >= deadline:
            break
        print(f"[fetch] {category}...")
        try:
            articles = scraper.fetch_popular_articles(category, limit=30)
            new = 0
            for a in articles:
                if a.get("url") and a["url"] not in seen_urls:
                    all_articles.append(a)
                    seen_urls.add(a["url"])
                    new += 1
            print(f"  +{new} new (total {len(all_articles)})")
        except Exception as e:
            print(f"  error: {e}")
        time.sleep(2)

    # Save checkpoint
    cumulative_log.write_text(
        json.dumps(all_articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[checkpoint] {len(all_articles)} articles saved")

    # Phase B: fetch detail for top 30 articles to enrich structure analysis
    print("\n[phase B] fetching details for top performers")
    top = sorted(all_articles, key=lambda a: a.get("likes", 0), reverse=True)[:30]
    for i, art in enumerate(top, 1):
        if datetime.now() >= deadline:
            break
        url = art.get("url", "")
        if not url or "word_count" in art:
            continue
        try:
            detail = scraper.fetch_article_detail(url)
            art.update(detail)
            print(f"  [{i}/30] {art.get('title','')[:40]} words={detail.get('word_count',0)} h2={detail.get('h2_count',0)}")
        except Exception as e:
            print(f"  [{i}] error: {e}")
        time.sleep(2.5)

    # Final save
    cumulative_log.write_text(
        json.dumps(all_articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Re-analyze with enriched data
    print(f"\n[analyze] {len(all_articles)} total articles")
    patterns = extractor.extract_winning_patterns(all_articles)
    kb_path = updater.update_knowledge_base(patterns)
    sg_path = updater.suggest_prompt_improvements(patterns)
    print(f"  knowledge: {kb_path}")
    print(f"  suggestions: {sg_path}")
    print(f"[done] {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
