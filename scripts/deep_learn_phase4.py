"""Phase 4: Maximum breadth scraping + meta-analysis."""

from __future__ import annotations

import io
import json
import sys
import time
from collections import Counter
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


MORE_CATEGORIES = [
    # Niche high-value topics
    "エッセイ", "日記", "note公式", "コラム", "感想",
    "今日のTips", "お金", "家計簿", "ふるさと納税",
    "マインドフルネス", "ワーケーション", "在宅ワーク",
    "レシピ", "お弁当", "スイーツ", "パン",
    "アート", "デザイン", "タイポグラフィ", "UI",
    "心理学", "哲学", "歴史", "科学",
    "ニュース", "政治", "社会", "時事",
    "SEO", "ブログ", "Webライティング", "コピーライティング",
    "Python", "JavaScript", "Web開発", "アプリ開発",
    "AI活用", "GPT", "画像AI", "動画AI",
    "ガジェット", "Apple", "iPhone", "MacBook",
    "note術", "ライフハック", "効率化", "時間管理",
    "恋愛相談", "失恋", "出会い",
    "独立", "起業家", "経営",
]


def main() -> None:
    deadline = datetime.now().replace(hour=23, minute=53, second=0, microsecond=0)
    print(f"[phase4] until {deadline.isoformat()}")

    scraper = NoteScraper()
    extractor = PatternExtractor()
    updater = PromptUpdater()

    cumulative_log = _ROOT / "docs" / "knowledge" / "note-trends" / "cumulative.json"
    all_articles = json.loads(cumulative_log.read_text(encoding="utf-8"))
    print(f"[loaded] {len(all_articles)} articles")

    seen_urls = {a.get("url") for a in all_articles if a.get("url")}

    for category in MORE_CATEGORIES:
        if datetime.now() >= deadline:
            print("[timeout]")
            break
        try:
            articles = scraper.fetch_popular_articles(category, limit=30)
            new = 0
            for a in articles:
                if a.get("url") and a["url"] not in seen_urls:
                    all_articles.append(a)
                    seen_urls.add(a["url"])
                    new += 1
            print(f"  {category}: +{new} (total {len(all_articles)})")
        except Exception as e:
            print(f"  {category}: error {e}")
        time.sleep(2)

    # Save
    cumulative_log.write_text(
        json.dumps(all_articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Generate mega summary
    print(f"\n[mega analysis] {len(all_articles)} articles")
    patterns = extractor.extract_winning_patterns(all_articles)
    updater.update_knowledge_base(patterns)
    updater.suggest_prompt_improvements(patterns)

    # Additional insight: top authors
    author_counter = Counter()
    for a in all_articles:
        author = a.get("author", "")
        if author:
            author_counter[author] += a.get("likes", 0)
    top_authors = author_counter.most_common(20)

    authors_path = _ROOT / "docs" / "knowledge" / "note-trends" / "top_authors.md"
    lines = [
        f"# Top Authors by Total Likes ({datetime.now().strftime('%Y-%m-%d')})",
        "",
    ]
    for author, total_likes in top_authors:
        lines.append(f"- **{author}**: ♥{total_likes:,}")
    authors_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  saved: {authors_path}")

    # Length distribution of top articles
    top100 = sorted(all_articles, key=lambda a: a.get("likes", 0), reverse=True)[:100]
    with_words = [a for a in top100 if a.get("word_count", 0) > 0]
    if with_words:
        avg_words = sum(a["word_count"] for a in with_words) / len(with_words)
        lengths = [a["word_count"] for a in with_words]
        print(f"[top100 stats] avg_words={avg_words:.0f}, min={min(lengths)}, max={max(lengths)}")

    print(f"[done] {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
