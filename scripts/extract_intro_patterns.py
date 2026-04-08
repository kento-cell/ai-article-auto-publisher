"""Extract opening/intro patterns from top free articles."""

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


def get_clean_intro(preview: str, title: str) -> str:
    """Strip title/date/author from preview to get the actual body opening."""
    if not preview:
        return ""
    text = preview
    # Remove the title if it's repeated
    text = text.replace(title, "", 1)
    # Remove typical metadata
    text = re.sub(r"^\s*\d{1,3},?\d{3}\s*", "", text)  # like count
    text = re.sub(r"\d{4}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}", "", text)
    text = re.sub(r"Photo by\s+\S+", "", text)
    text = text.strip()
    return text[:300]


def main() -> None:
    data = json.loads((KB / "cumulative.json").read_text(encoding="utf-8"))
    top = sorted([a for a in data if not a.get("is_paid") and a.get("preview")],
                 key=lambda a: a.get("likes", 0), reverse=True)[:100]

    # Categorize opening patterns
    patterns = Counter()
    samples = []

    for a in top:
        preview = a.get("preview", "")
        title = a.get("title", "")
        intro = get_clean_intro(preview, title)
        if not intro:
            continue
        first_50 = intro[:50]

        # Pattern detection
        found = []
        if re.search(r"こんにちは|こんばんは|はじめまして", first_50):
            found.append("挨拶型")
        if re.search(r"(皆さん|みなさん|あなた)", first_50):
            found.append("読者呼びかけ型")
        if re.search(r"先日|昨日|今日|最近|この前|先週", first_50):
            found.append("時系列型")
        if re.search(r"[？?]", first_50):
            found.append("疑問提起型")
        if re.search(r"^[0-9０-９]", intro):
            found.append("数字開始型")
        if re.search(r"突然|いきなり|ふと", first_50):
            found.append("意外性型")
        if re.search(r"(思い|考え|感じ).{0,5}ました", first_50):
            found.append("体験語り型")
        if re.search(r"(結論|まず|最初に|本記事)", first_50):
            found.append("結論先出し型")
        if "私" in first_50 or "僕" in first_50 or "俺" in first_50:
            found.append("一人称型")

        if not found:
            found.append("その他")

        for p in found:
            patterns[p] += 1

        if len(samples) < 10 and found[0] != "その他":
            samples.append({
                "pattern": found[0],
                "title": title[:40],
                "intro": intro[:150],
                "likes": a.get("likes", 0),
            })

    report = [
        f"# 書き出しパターン分析 ({datetime.now().strftime('%Y-%m-%d')})",
        "",
        f"## 対象: トップ無料記事 100件",
        "",
        "## 書き出しパターン分布",
        "",
    ]
    for pat, count in patterns.most_common():
        report.append(f"- **{pat}**: {count}件 ({count}%)")

    report += [
        "",
        "## サンプル（人気順）",
        "",
    ]
    for s in samples:
        report.append(f"### [{s['pattern']}] ♥{s['likes']} {s['title']}")
        report.append(f"> {s['intro']}")
        report.append("")

    out = KB / f"{datetime.now().strftime('%Y-%m-%d')}_intro_patterns.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"[saved] {out}")
    print("\n".join(report[:30]))


if __name__ == "__main__":
    main()
