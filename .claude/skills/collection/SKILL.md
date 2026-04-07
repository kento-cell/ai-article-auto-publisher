---
name: collection
description: Use when collecting articles from external sources and calculating trend scores. Handles arXiv, Reddit, and trend detection.
---

# Collection Skill

## Purpose

外部ソースから記事を収集し、トレンドスコアで優先順位をつける。

---

## Workflow

1. Load `core` skill first for context.
2. Read `config/settings.yaml` → `collection` section.
3. Execute collectors based on target platform:
   - **Zenn向け**: `ArxivCollector` (cs.AI, cs.CL, cs.LG, cs.CV)
   - **note向け**: `RedditCollector` (programming, ML, AI, tech)
4. Calculate trend scores via `TrendDetector`.
5. Rank articles by score, filter by `max_articles`.
6. Log results to session file.

---

## Modules

| Module | Class | Role |
|--------|-------|------|
| `collectors/base_collector.py` | `BaseCollector` | 共通インターフェース |
| `collectors/arxiv_collector.py` | `ArxivCollector` | arXiv論文取得 |
| `collectors/reddit_collector.py` | `RedditCollector` | Reddit投稿取得 |
| `collectors/trend_detector.py` | `TrendDetector` | スコア計算・ランキング |

---

## Trend Score Factors

- **Recency (40%)**: 48時間半減期の指数減衰
- **Social Signals (35%)**: スコア + コメント数
- **Source Authority (25%)**: ソース別重みづけ

---

## Rules

- Rate limitを遵守する（arXiv: 3秒間隔）
- Reddit APIはJSON endpoint（認証不要）を使用
- 収集失敗は個別スキップ、パイプライン全体は停止しない
- 0件収集時はログに警告を出してパイプラインを早期終了

---

## Output

List of ranked articles, each containing:
- `title`, `url`, `source`, `content`, `authors`, `published_date`
- `trend_score` (0-100)

---

## STOP CONDITION

- 全ソースの収集が完了したら停止。
- 収集エラーが全ソースで発生した場合、早期停止。
