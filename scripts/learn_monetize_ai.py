"""Focused learning: monetization methods + AI catch-up."""

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


# Monetization-specific queries
MONETIZE_QUERIES = [
    "副業", "稼ぐ", "マネタイズ", "収益化", "月収",
    "アフィリエイト", "情報商材", "Brain", "Tips",
    "Kindle出版", "KDP", "note有料記事",
    "Udemy", "スキル販売", "ココナラ",
    "YouTube収益", "TikTok収益", "Instagram収益",
    "ブログ収益", "SEO集客",
    "FIRE", "投資収益", "配当金",
]

# AI catch-up queries
AI_QUERIES = [
    "ChatGPT", "Claude", "Gemini", "GPT-5", "Claude Code",
    "生成AI", "LLM", "AIエージェント", "プロンプトエンジニアリング",
    "Stable Diffusion", "Midjourney", "画像生成AI",
    "AI自動化", "n8n", "Zapier", "Make",
    "AI副業", "AIマネタイズ", "AIツール",
    "Cursor", "GitHub Copilot", "Bolt",
    "MCP", "Function Calling", "RAG",
    "Notion AI", "Perplexity",
]


def main() -> None:
    print(f"[start] {datetime.now().isoformat()}")

    scraper = NoteScraper()
    cumulative_log = KB / "cumulative.json"
    all_articles = []
    if cumulative_log.exists():
        try:
            all_articles = json.loads(cumulative_log.read_text(encoding="utf-8"))
            print(f"[loaded] {len(all_articles)} existing articles")
        except Exception:
            pass

    seen_urls = {a.get("url") for a in all_articles if a.get("url")}
    queries = MONETIZE_QUERIES + AI_QUERIES
    print(f"[queries] {len(queries)} topics to scrape")

    new_articles: list[dict] = []
    for q in queries:
        try:
            articles = scraper.fetch_popular_articles(q, limit=30)
            added = 0
            for a in articles:
                if a.get("url") and a["url"] not in seen_urls:
                    all_articles.append(a)
                    new_articles.append(a)
                    seen_urls.add(a["url"])
                    added += 1
            print(f"  {q}: +{added}")
        except Exception as e:
            print(f"  {q}: error {e}")
        time.sleep(2)

    # Save
    cumulative_log.write_text(
        json.dumps(all_articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[total] {len(all_articles)} articles ({len(new_articles)} new)")

    # Focused analysis: paid articles in these topics
    monetize_articles = [
        a for a in all_articles
        if any(
            q in (a.get("title", "") + a.get("summary", ""))
            for q in MONETIZE_QUERIES
        )
    ]
    ai_articles = [
        a for a in all_articles
        if any(
            q in (a.get("title", "") + a.get("summary", ""))
            for q in AI_QUERIES
        )
    ]

    paid_monetize = [a for a in monetize_articles if a.get("is_paid")]
    paid_ai = [a for a in ai_articles if a.get("is_paid")]

    # Top earners by price × likes heuristic
    def _score(a: dict) -> float:
        return a.get("likes", 0) * max(a.get("price", 1), 1) / 1000

    top_monetize = sorted(paid_monetize, key=_score, reverse=True)[:20]
    top_ai = sorted(paid_ai, key=_score, reverse=True)[:20]

    # Extract keywords from titles
    def _keywords(articles: list[dict], top_n: int = 30) -> list:
        counter = Counter()
        for a in articles:
            tokens = re.findall(r"[一-龥]{2,}|[ぁ-ん]{4,}|[ァ-ヴー]{3,}|[a-zA-Z]{3,}", a.get("title", ""))
            for t in tokens:
                counter[t] += 1
        return counter.most_common(top_n)

    # Build report
    report = [
        f"# マネタイズ & AI フォーカスレポート ({datetime.now().strftime('%Y-%m-%d')})",
        "",
        f"## サマリー",
        f"- 総記事数: {len(all_articles)}",
        f"- 新規追加: {len(new_articles)}",
        f"- マネタイズ関連: {len(monetize_articles)}件（有料{len(paid_monetize)}件）",
        f"- AI関連: {len(ai_articles)}件（有料{len(paid_ai)}件）",
        "",
        "## 💰 マネタイズ系トップ有料記事",
        "",
    ]
    for a in top_monetize[:15]:
        report.append(
            f"- ¥{a.get('price',0)} ♥{a.get('likes',0)} [{a.get('title','')[:60]}]({a.get('url','')})"
        )

    report += [
        "",
        "## 🤖 AI系トップ有料記事",
        "",
    ]
    for a in top_ai[:15]:
        report.append(
            f"- ¥{a.get('price',0)} ♥{a.get('likes',0)} [{a.get('title','')[:60]}]({a.get('url','')})"
        )

    report += [
        "",
        "## 💰 マネタイズ系頻出キーワード",
        "",
    ]
    for word, count in _keywords(monetize_articles, 30):
        report.append(f"- {word}: {count}")

    report += [
        "",
        "## 🤖 AI系頻出キーワード",
        "",
    ]
    for word, count in _keywords(ai_articles, 30):
        report.append(f"- {word}: {count}")

    # Price distribution for paid articles
    if paid_monetize or paid_ai:
        report += [
            "",
            "## 💴 価格帯分布",
            "",
            "### マネタイズ系",
        ]
        prices = sorted(a.get("price", 0) for a in paid_monetize if a.get("price", 0))
        if prices:
            report += [
                f"- 最低: ¥{min(prices)}",
                f"- 最高: ¥{max(prices)}",
                f"- 中央値: ¥{prices[len(prices)//2]}",
                f"- 平均: ¥{sum(prices)//len(prices)}",
            ]
        report.append("")
        report.append("### AI系")
        prices = sorted(a.get("price", 0) for a in paid_ai if a.get("price", 0))
        if prices:
            report += [
                f"- 最低: ¥{min(prices)}",
                f"- 最高: ¥{max(prices)}",
                f"- 中央値: ¥{prices[len(prices)//2]}",
                f"- 平均: ¥{sum(prices)//len(prices)}",
            ]

    out = KB / f"{datetime.now().strftime('%Y-%m-%d')}_monetize_ai_focus.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"[saved] {out}")
    print(f"[done] {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
