"""Update knowledge base from learned patterns."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_KNOWLEDGE_DIR = _REPO_ROOT / "docs" / "knowledge" / "note-trends"


class PromptUpdater:
    """Convert pattern analysis into knowledge base entries + prompt suggestions."""

    def __init__(self) -> None:
        _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    def update_knowledge_base(self, patterns: dict[str, Any]) -> Path:
        """Save analysis results as a Markdown knowledge entry."""
        date = datetime.now().strftime("%Y-%m-%d")
        out = _KNOWLEDGE_DIR / f"{date}_auto_learning.md"

        title_a = patterns.get("title_analysis", {})
        struct_a = patterns.get("structure_analysis", {})
        top = patterns.get("top_performers", [])
        tags = patterns.get("tags_distribution", [])
        paid_ratio = patterns.get("paid_ratio", 0.0)

        lines = [
            f"# Auto Learning Report ({date})",
            "",
            "## タイトル分析",
            f"- サンプル数: {title_a.get('total_titles', 0)}",
            f"- 平均文字数: {title_a.get('avg_length', 0):.1f}",
            f"- 絵文字使用率: {title_a.get('emoji_usage_rate', 0):.0%}",
            f"- 数字使用率: {title_a.get('number_usage_rate', 0):.0%}",
            "",
            "### よく使われるパターン",
        ]
        for phrase, count in title_a.get("common_phrases", []):
            lines.append(f"- {phrase}: {count}件")
        lines += [
            "",
            "### サンプルタイトル（人気上位）",
        ]
        for t in title_a.get("sample_titles", [])[:10]:
            lines.append(f"- {t}")

        lines += [
            "",
            "## 構造分析",
            f"- 平均H2数: {struct_a.get('avg_h2_count', 0):.1f}",
            f"- 平均文字数: {struct_a.get('avg_word_count', 0):.0f}",
            f"- 平均画像数: {struct_a.get('avg_image_count', 0):.1f}",
            f"- 推奨文字数範囲: {struct_a.get('optimal_word_range', (1500, 4000))}",
            "",
            f"## 有料記事比率: {paid_ratio:.0%}",
            "",
            "## トップ記事 TOP10",
        ]
        for i, a in enumerate(top[:10], 1):
            lines.append(f"{i}. [{a.get('title', '')[:60]}]({a.get('url', '')}) — ♥{a.get('likes', 0)}")

        lines += [
            "",
            "## タグ分布 TOP20",
        ]
        for tag, count in tags[:20]:
            lines.append(f"- #{tag}: {count}")

        out.write_text("\n".join(lines), encoding="utf-8")
        return out

    def suggest_prompt_improvements(self, patterns: dict[str, Any]) -> Path:
        """Save actionable prompt improvement suggestions."""
        out = _KNOWLEDGE_DIR / "prompt_suggestions.md"
        title_a = patterns.get("title_analysis", {})
        struct_a = patterns.get("structure_analysis", {})

        suggestions = [
            "# プロンプト改善提案（自動生成）",
            f"_最終更新: {datetime.now().isoformat()}_",
            "",
            "## タイトル生成への反映",
        ]
        avg_len = title_a.get("avg_length", 30)
        suggestions.append(f"- タイトルは{int(avg_len-5)}〜{int(avg_len+5)}文字を目安に")
        if title_a.get("number_usage_rate", 0) > 0.4:
            suggestions.append("- 数字を含めると訴求力UP（人気記事の40%以上が使用）")
        if title_a.get("emoji_usage_rate", 0) > 0.3:
            suggestions.append("- 絵文字を1個入れる（人気記事の30%以上が使用）")

        suggestions += [
            "",
            "## 採用すべきフレーズパターン",
        ]
        for phrase, count in title_a.get("common_phrases", [])[:5]:
            suggestions.append(f"- 「{phrase}」型 — {count}件で使用")

        suggestions += [
            "",
            "## 構造への反映",
            f"- H2見出しは{int(struct_a.get('avg_h2_count', 4))}個程度を目安",
            f"- 文字数: {int(struct_a.get('avg_word_count', 2500))}字程度",
            "",
            "## 適用方法",
            "上記の分析結果を `config/prompts.yaml` に手動反映してください。",
            "自動上書きは安全のため行いません。",
        ]

        out.write_text("\n".join(suggestions), encoding="utf-8")
        return out
