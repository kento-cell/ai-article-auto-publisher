---
name: self-improvement
description: Use after pipeline completion or failure to extract learnings, update patterns, and improve future runs.
---

# Self Improvement Skill

## Purpose

パイプライン実行後の振り返りを行い、再利用可能なパターンを蓄積する。

---

## Trigger

- パイプライン実行が完了した時
- 品質評価で繰り返し不合格パターンが観測された時
- 投稿エラーが発生した時（特にUI変更起因）
- トレンド予測精度を振り返る時

---

## Workflow

1. パイプライン実行ログを読み込む。
2. 以下のパターンを検出:
   - 品質不合格の共通原因（引用不足、構成問題等）
   - トレンドスコアと実際の反応の相関
   - 投稿失敗の根本原因
   - トークン消費の異常パターン
3. High-signal な知見を記録する。
4. 必要に応じて設定・プロンプトの改善案を提示する。

---

## Knowledge Categories

| Category | Storage | Example |
|----------|---------|---------|
| 品質パターン | `docs/knowledge/quality_*.md` | 不合格になりやすい記事構成 |
| トレンド知見 | `docs/knowledge/trend_*.md` | 高スコア記事の共通特徴 |
| 投稿トラブル | `docs/knowledge/publish_*.md` | UI変更への対処法 |
| プロンプト改善 | `docs/knowledge/prompt_*.md` | 効果的なプロンプトパターン |

---

## Rules

- 毎回実行しない。明確な学習シグナルがある時だけ。
- タスク固有の詳細は `docs/sessions/` に記録。
- 安定した再利用可能パターンのみ `docs/knowledge/` に昇格。
- 既存のknowledgeファイルがあれば更新を優先（新規作成より）。
- 短く具体的な記録を心がける（長文の振り返りは不要）。

---

## Metrics to Track

- 品質スコア平均の推移（週次）
- 合格率の推移
- プラットフォーム別投稿成功率
- トークン消費効率（記事あたりトークン数）
- トレンドスコア上位記事のPV/反応（手動入力）

---

## STOP CONDITION

- 学習シグナルが低い場合は記録しない。
- 既知のパターンを重複記録しない。
