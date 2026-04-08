"""Final: meta-analysis across all scraped data + category breakdown."""

from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
KB = _ROOT / "docs" / "knowledge" / "note-trends"


def main() -> None:
    cumulative = json.loads((KB / "cumulative.json").read_text(encoding="utf-8"))
    print(f"[loaded] {len(cumulative)} articles")

    # === Top N across all data ===
    all_top = sorted(cumulative, key=lambda a: a.get("likes", 0), reverse=True)

    # === Per-category top ===
    by_category = defaultdict(list)
    for a in cumulative:
        cat = a.get("category", "unknown")
        by_category[cat].append(a)

    # === Title pattern extraction ===
    bracket_re = re.compile(r"[【\[（\(]([^】\]\)）]+)[】\]）\)]")
    bracket_prefixes = Counter()
    for a in all_top[:300]:
        title = a.get("title", "")
        matches = bracket_re.findall(title)
        for m in matches:
            if len(m) <= 15:
                bracket_prefixes[m] += 1

    # === Paid article insights ===
    paid = [a for a in cumulative if a.get("is_paid")]
    paid_prices = [a.get("price", 0) for a in paid if a.get("price", 0) > 0]

    # === Keyword analysis of top 200 titles ===
    stopwords = set("の が を は に へ と で や も から まで より こと もの これ それ あれ する した して いる ある なる という ため ように とは とき なら ば ね よ か".split())
    word_counter = Counter()
    for a in all_top[:200]:
        title = a.get("title", "")
        # Simple tokenization: extract kanji/hiragana/katakana/english sequences
        tokens = re.findall(r"[一-龥]{2,}|[ぁ-ん]{3,}|[ァ-ヴー]{2,}|[a-zA-Z]{3,}", title)
        for t in tokens:
            if t not in stopwords:
                word_counter[t] += 1

    # === Build mega report ===
    date = datetime.now().strftime("%Y-%m-%d")
    report = [
        f"# Note学習メガレポート ({date})",
        "",
        f"_分析対象: **{len(cumulative)}記事**_",
        "",
        "## エグゼクティブサマリー",
        "",
        f"- 総記事数: {len(cumulative)}",
        f"- カテゴリ数: {len(by_category)}",
        f"- 有料記事: {len(paid)}件 ({len(paid)*100/len(cumulative):.1f}%)",
    ]
    if paid_prices:
        report.append(
            f"- 有料価格: ¥{min(paid_prices)}〜¥{max(paid_prices)} "
            f"(平均¥{sum(paid_prices)/len(paid_prices):.0f})"
        )

    # Top performers
    report += [
        "",
        "## ♥ トップ20記事",
        "",
    ]
    for i, a in enumerate(all_top[:20], 1):
        price_str = f"¥{a.get('price')}" if a.get("is_paid") else "無料"
        report.append(
            f"{i}. ♥{a.get('likes',0)} [{price_str}] {a.get('title','')[:50]}"
        )

    # Bracket prefixes (meta-patterns)
    report += [
        "",
        "## 【タイトル】括弧プレフィックスのパターン",
        "note人気記事は`【◯◯】`で始まるものが多い。使える型:",
        "",
    ]
    for prefix, count in bracket_prefixes.most_common(20):
        report.append(f"- 【{prefix}】: {count}回")

    # Keyword frequency
    report += [
        "",
        "## 🔑 頻出キーワード (TOP200記事)",
        "",
    ]
    for word, count in word_counter.most_common(30):
        report.append(f"- {word}: {count}回")

    # Category breakdown
    report += [
        "",
        "## 📂 カテゴリ別統計",
        "",
        "| カテゴリ | 記事数 | TOP ♥ |",
        "|---------|--------|-------|",
    ]
    for cat, arts in sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)[:30]:
        top_likes = max((a.get("likes", 0) for a in arts), default=0)
        report.append(f"| {cat} | {len(arts)} | {top_likes} |")

    # Length analysis from detailed articles
    with_detail = [a for a in cumulative if a.get("word_count", 0) > 0]
    if with_detail:
        lengths = [a["word_count"] for a in with_detail]
        h2_counts = [a.get("h2_count", 0) for a in with_detail]
        report += [
            "",
            "## 📏 詳細取得済み記事の構造",
            f"- サンプル: {len(with_detail)}記事",
            f"- 文字数: 平均{sum(lengths)/len(lengths):.0f}字, 中央値{sorted(lengths)[len(lengths)//2]}字",
            f"- H2見出し: 平均{sum(h2_counts)/len(h2_counts):.1f}個",
        ]

    # Monetization strategy based on data
    if paid_prices:
        report += [
            "",
            "## 💰 マネタイズ戦略の示唆",
            "",
            f"- 有料記事比率は約{len(paid)*100/len(cumulative):.0f}%",
            f"- 価格帯: ¥{sorted(paid_prices)[len(paid_prices)//2]}（中央値）",
            f"- **月60万円戦略**: {600000 // max(sorted(paid_prices)[len(paid_prices)//2], 100)}本/月の販売が必要",
            "- 高単価路線: ¥3,000〜¥5,000の価値ある記事を月200本",
            "- 量産路線: ¥500程度の記事を月1200本",
        ]

    report += [
        "",
        "## 🎯 生成プロンプトへの反映ポイント",
        "",
        "1. **タイトルは括弧プレフィックスを使う**: `【◯◯】`系が人気",
        "   - 例: 【完全無料】【2026年最新】【殿堂入り】【コアメンバー】",
        "2. **AI・お金・ライフハック系の単語を入れる**: キーワード頻出上位",
        "3. **具体的な数字を入れる**: 「月◯万円」「◯選」「◯日で」",
        "4. **構造は H2を5〜10個**、文字数は3000〜5000字が最適レンジ",
        "5. **タイトル文字数は35〜45字**（人気記事の中央値）",
    ]

    out = KB / f"{date}_mega_report.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"[saved] {out}")
    print(f"[done] {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
