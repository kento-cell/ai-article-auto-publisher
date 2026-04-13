"""Extract monetization methods mentioned in scraped article content."""

from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
KB = _ROOT / "docs" / "knowledge" / "note-trends"

# Keywords indicating monetization methods
MONETIZATION_KEYWORDS = {
    # Platforms (other than note)
    "プラットフォーム": [
        "Udemy", "Brain", "Tips", "codoc", "Kindle", "BASE", "STORES",
        "BOOTH", "pixivFANBOX", "Fantia", "Patreon", "Ko-fi",
        "Shopify", "Gumroad", "Substack", "Bubble", "Glide",
        "Zenn Books", "SKIMA", "ココナラ", "ストアカ", "UDEMY",
    ],
    "アフィリエイト": [
        "Amazonアソシエイト", "楽天アフィリエイト", "A8", "もしもアフィリエイト",
        "バリューコマース", "afb", "アフィリ", "ASP", "PayPay",
        "afb", "アクセストレード", "ImpactRadius",
    ],
    "広告": [
        "AdSense", "Google広告", "YouTube広告", "アドセンス",
        "インプレッション", "広告収益", "PV収益",
    ],
    "動画・配信": [
        "YouTube", "TikTok", "Instagram", "Reels", "Shorts",
        "ライブ配信", "ふわっち", "ツイキャス", "17LIVE", "Pococha",
        "Twitch", "ニコ生",
    ],
    "スキル販売": [
        "ココナラ", "Lancers", "CrowdWorks", "タイムチケット",
        "MENTA", "TimeTicket", "Bizseek",
    ],
    "デジタルコンテンツ": [
        "電子書籍", "KDP", "オンライン講座", "eラーニング",
        "テンプレート販売", "Notionテンプレート", "配布",
    ],
    "SNS": [
        "X収益化", "Twitter収益化", "Xプレミアム", "クリエイター報酬",
        "Instagramリール", "TikTok Creator Fund",
    ],
    "仮想通貨・投資": [
        "仮想通貨", "暗号資産", "Bitcoin", "NFT", "DeFi",
        "NISA", "iDeCo", "インデックス投資", "高配当株",
    ],
    "副業": [
        "副業", "せどり", "転売", "不用品", "メルカリ",
        "クラウドソーシング", "Web制作", "記事作成代行",
    ],
    "AI活用": [
        "プロンプト販売", "GPT", "画像生成AI販売", "AIツール作成",
        "自動化ツール", "スクレイピング", "RPA",
    ],
}


def main() -> None:
    data = json.loads((KB / "cumulative.json").read_text(encoding="utf-8"))
    print(f"[loaded] {len(data)} articles")

    # Collect all searchable text from each article
    matches = {category: Counter() for category in MONETIZATION_KEYWORDS}
    article_mentions = {}  # keyword -> list of (title, likes)

    for art in data:
        text = " ".join([
            art.get("title", ""),
            art.get("summary", ""),
            art.get("preview", ""),
            " ".join(art.get("tags", [])),
        ])
        for category, keywords in MONETIZATION_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    matches[category][kw] += 1
                    article_mentions.setdefault(kw, []).append({
                        "title": art.get("title", ""),
                        "likes": art.get("likes", 0),
                        "url": art.get("url", ""),
                    })

    # Build report
    report = [
        f"# マネタイズ手法抽出 ({datetime.now().strftime('%Y-%m-%d')})",
        "",
        f"## 分析対象: {len(data)}記事",
        "",
        "## カテゴリ別・言及回数",
        "",
    ]
    for category, counter in matches.items():
        total = sum(counter.values())
        if total == 0:
            continue
        report.append(f"### {category} (合計{total}件)")
        for kw, count in counter.most_common(10):
            report.append(f"- **{kw}**: {count}件")
        report.append("")

    # Top mentioning articles for each keyword
    report += [
        "## キーワード別トップ記事",
        "",
    ]
    all_keywords = []
    for category, counter in matches.items():
        for kw, count in counter.most_common(3):
            all_keywords.append((category, kw, count))
    all_keywords.sort(key=lambda x: x[2], reverse=True)

    for category, kw, count in all_keywords[:30]:
        mentions = article_mentions.get(kw, [])
        mentions.sort(key=lambda a: a["likes"], reverse=True)
        report.append(f"### [{category}] {kw} ({count}件)")
        for m in mentions[:3]:
            report.append(f"- ♥{m['likes']} [{m['title'][:50]}]({m['url']})")
        report.append("")

    out = KB / f"{datetime.now().strftime('%Y-%m-%d')}_monetization_methods.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"[saved] {out}")

    # Print summary
    print("\n=== Monetization mentions summary ===")
    for category, counter in matches.items():
        total = sum(counter.values())
        if total > 0:
            print(f"  {category}: {total}件")
            for kw, count in counter.most_common(5):
                print(f"    - {kw}: {count}")


if __name__ == "__main__":
    main()
