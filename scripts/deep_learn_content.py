"""Phase: Learn from actual article content (not just metadata)."""

from __future__ import annotations

import io
import json
import re
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

KB = _ROOT / "docs" / "knowledge" / "note-trends"


def main() -> None:
    cumulative = json.loads((KB / "cumulative.json").read_text(encoding="utf-8"))
    print(f"[loaded] {len(cumulative)} articles")

    scraper = NoteScraper()
    top = sorted(cumulative, key=lambda a: a.get("likes", 0), reverse=True)

    # Free articles (no paid section) - full content accessible
    free_top = [a for a in top if not a.get("is_paid")][:50]
    print(f"[free top] {len(free_top)} articles to study")

    # Fetch content previews for those without them
    studied = []
    for i, art in enumerate(free_top, 1):
        url = art.get("url", "")
        if not url:
            continue
        try:
            if "preview" not in art:
                detail = scraper.fetch_article_detail(url)
                art.update(detail)
                time.sleep(2)
            studied.append(art)
            print(f"  [{i}/{len(free_top)}] ♥{art.get('likes',0)} words={art.get('word_count',0)}")
        except Exception as e:
            print(f"  [{i}] error: {e}")

    # Save updated data
    (KB / "cumulative.json").write_text(
        json.dumps(cumulative, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Analyze intro patterns (first 200 chars of each top article)
    print("\n[intro analysis]")
    intros = []
    for art in studied:
        preview = art.get("preview", "")
        if preview:
            intros.append(preview[:200])

    # Find common opening patterns
    opening_words = Counter()
    for intro in intros:
        # First sentence
        sentences = re.split(r"[。！？\n]", intro)
        if sentences and sentences[0]:
            first = sentences[0].strip()[:30]
            if first:
                # Extract starting patterns
                if first.startswith("こんにちは"):
                    opening_words["挨拶（こんにちは）"] += 1
                if "皆さん" in first[:15] or "みなさん" in first[:15]:
                    opening_words["皆さん呼びかけ"] += 1
                if "ですが" in first or "ですよね" in first:
                    opening_words["共感型"] += 1
                if first.startswith(("先日", "昨日", "今日", "最近")):
                    opening_words["時系列開始"] += 1
                if re.match(r"^[0-9]", first):
                    opening_words["数字開始"] += 1
                if "？" in first or "?" in first:
                    opening_words["疑問形"] += 1

    # Word frequency in content
    word_freq = Counter()
    for art in studied:
        preview = art.get("preview", "")
        tokens = re.findall(r"[一-龥]{2,}|[ぁ-ん]{4,}|[ァ-ヴー]{3,}", preview)
        for t in tokens:
            word_freq[t] += 1

    # Build content insights report
    report = [
        f"# 本文学習レポート ({datetime.now().strftime('%Y-%m-%d')})",
        "",
        f"## 分析対象: トップ無料記事 {len(studied)}件",
        "",
        "## 書き出しパターン",
    ]
    for pattern, count in opening_words.most_common(10):
        report.append(f"- {pattern}: {count}件")

    report += [
        "",
        "## 本文頻出語彙（TOP50）",
        "",
    ]
    for word, count in word_freq.most_common(50):
        if count >= 3:
            report.append(f"- {word}: {count}")

    # Sample intros from top performers
    report += [
        "",
        "## トップ記事の書き出しサンプル",
        "",
    ]
    for art in studied[:5]:
        preview = art.get("preview", "")[:150]
        if preview:
            report.append(f"### ♥{art.get('likes',0)} {art.get('title','')[:40]}")
            report.append(f"> {preview}...")
            report.append("")

    out = KB / f"{datetime.now().strftime('%Y-%m-%d')}_content_learning.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"[saved] {out}")
    print(f"[done] {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
