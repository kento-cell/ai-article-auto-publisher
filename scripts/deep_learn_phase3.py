"""Phase 3: Extended detail scraping + paid article analysis."""

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


def main() -> None:
    deadline = datetime.now().replace(hour=23, minute=55, second=0, microsecond=0)
    print(f"[phase3 start] until {deadline.isoformat()}")

    scraper = NoteScraper()
    extractor = PatternExtractor()
    updater = PromptUpdater()

    cumulative_log = _ROOT / "docs" / "knowledge" / "note-trends" / "cumulative.json"
    all_articles = json.loads(cumulative_log.read_text(encoding="utf-8"))
    print(f"[loaded] {len(all_articles)} articles")

    # Expand detail scraping to top 100
    top = sorted(all_articles, key=lambda a: a.get("likes", 0), reverse=True)
    detail_needed = [a for a in top[:100] if "word_count" not in a]
    print(f"[phase A] fetching {len(detail_needed)} more detail pages")

    for i, art in enumerate(detail_needed, 1):
        if datetime.now() >= deadline:
            print("[timeout]")
            break
        url = art.get("url", "")
        if not url:
            continue
        try:
            detail = scraper.fetch_article_detail(url)
            art.update(detail)
            print(f"  [{i}/{len(detail_needed)}] ♥{art.get('likes',0)} {art.get('title','')[:35]} w={detail.get('word_count',0)}")
        except Exception as e:
            print(f"  [{i}] error: {e}")
        time.sleep(2.0)

        if i % 20 == 0:
            cumulative_log.write_text(
                json.dumps(all_articles, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # Save
    cumulative_log.write_text(
        json.dumps(all_articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Analyze paid articles specifically
    paid = [a for a in all_articles if a.get("is_paid")]
    print(f"\n[paid analysis] {len(paid)} paid articles")
    if paid:
        prices = [a.get("price", 0) for a in paid]
        paid_patterns = extractor.extract_winning_patterns(paid)

        paid_report = _ROOT / "docs" / "knowledge" / "note-trends" / "paid_analysis.md"
        date = datetime.now().strftime("%Y-%m-%d")
        lines = [
            f"# 有料記事分析 ({date})",
            "",
            f"## サンプル数: {len(paid)}",
            f"- 価格範囲: ¥{min(prices)} 〜 ¥{max(prices)}",
            f"- 平均価格: ¥{sum(prices)/len(prices):.0f}",
            "",
            "## トップ有料記事",
        ]
        top_paid = sorted(paid, key=lambda a: a.get("likes", 0), reverse=True)[:15]
        for i, a in enumerate(top_paid, 1):
            lines.append(
                f"{i}. ¥{a.get('price',0)} ♥{a.get('likes',0)} [{a.get('title','')[:60]}]({a.get('url','')})"
            )

        lines += [
            "",
            "## 有料記事のタイトルパターン",
        ]
        ta = paid_patterns.get("title_analysis", {})
        for phrase, count in ta.get("common_phrases", []):
            lines.append(f"- {phrase}: {count}件")

        paid_report.write_text("\n".join(lines), encoding="utf-8")
        print(f"  saved: {paid_report}")

    # Final re-analysis
    patterns = extractor.extract_winning_patterns(all_articles)
    kb_path = updater.update_knowledge_base(patterns)
    sg_path = updater.suggest_prompt_improvements(patterns)
    print(f"\n[final] knowledge: {kb_path}")
    print(f"[final] suggestions: {sg_path}")
    print(f"[done] {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
