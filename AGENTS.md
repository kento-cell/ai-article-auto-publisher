# Agent Operating Guide

## Purpose

AI記事自動生成・投稿システムのエージェント運用ガイド。
収集→生成→品質評価→投稿のパイプラインをAIエージェントが自律運用する。

## Entry Workflow

1. Read `docs/sessions/LATEST.md` first for immediate context recovery.
2. If `LATEST.md` is missing or stale, read the newest `docs/sessions/YYYYMMDD_*.md` file.
3. Read `config/settings.yaml` for current system configuration.
4. Read `AI_CONTEXT.md` for repository structure understanding.

## Local Skill Set

Keep the repository-local skills under `.codex/skills/<skill-name>/SKILL.md`.

The current intended local skill set is:

- `.codex/skills/core/SKILL.md` — コンテキスト復元・基本行動
- `.codex/skills/collection/SKILL.md` — 記事収集・トレンド分析
- `.codex/skills/generation/SKILL.md` — 記事生成・LLM連携
- `.codex/skills/quality-gate/SKILL.md` — 品質評価・エビデンス検証
- `.codex/skills/publishing/SKILL.md` — 投稿・通知
- `.codex/skills/self-improvement/SKILL.md` — 振り返り・学習

## Pipeline Workflow

```
[Collection] → [Generation] → [Quality Gate] → [Publishing]
     ↑                                              |
     └──── self-improvement (feedback loop) ────────┘
```

### Phase 1: Collection（収集）
- Trigger: 毎日22:00 または手動実行
- Skill: `collection`
- Input: ソース設定 (settings.yaml)
- Output: ランク付きトレンド記事リスト

### Phase 2: Generation（生成）
- Trigger: 収集完了後
- Skill: `generation`
- Input: ランク付き記事 + プロンプトテンプレート
- Output: 生成記事（Markdown）

### Phase 3: Quality Gate（品質評価）
- Trigger: 生成完了後
- Skill: `quality-gate`
- Input: 生成記事
- Output: 評価スコア + 合否判定
- 不合格 → 再生成（最大2回）

### Phase 4: Publishing（投稿）
- Trigger: 品質合格後
- Skill: `publishing`
- Input: 合格記事
- Output: 投稿URL + Slack通知

## Operating Rules

- パイプラインの各フェーズは独立して実行可能にする。
- エラーが発生してもパイプライン全体を停止せず、該当記事をスキップする。
- トークン予算を常に確認し、超過時はローカルLLMにフォールバックする。
- 禁止フレーズ（settings.yaml参照）を含む記事は自動的に除外する。
- 引用・出典のない主張を含む記事は投稿しない。

## Token Budget Rules

- 週次上限: 2,000,000 tokens
- バッファ: 50%（実効上限: 3,000,000）
- 警告閾値: 80%
- 超過時: Ollama/CodeLlamaにフォールバック
- 毎週月曜 00:00 にリセット

## Memory Recovery Rules

- Treat `docs/sessions/LATEST.md` as the primary warm-start memory file.
- `LATEST.md` must contain at least:
  - Current Pipeline Status
  - Last Run Results (collected/generated/published counts)
  - Active Errors
  - Token Budget Status
  - Next Scheduled Run
  - Updated At (absolute date/time)

## Auto Logging Rules

- High-signal events to log automatically:
  - パイプライン実行結果（成功/失敗、件数）
  - 品質評価で不合格になったパターン
  - トークン消費の異常（急増、予算超過）
  - 新しいトレンドトピックの出現
  - 投稿エラー（UI変更等）
- Log to `docs/sessions/LATEST.md` immediately.
- Append details to `docs/sessions/YYYYMMDD_topic.md`.

## Output Contract

パイプライン実行レポートには以下を含める:

1. 実行日時
2. 収集結果（ソース別件数、トップトレンド）
3. 生成結果（プラットフォーム別、品質スコア）
4. 投稿結果（URL、価格設定）
5. エラーサマリー
6. トークン消費量
7. 次回推奨アクション

## Repository Layout

- `collectors/` — 記事収集モジュール
- `generators/` — 記事生成モジュール
- `publishers/` — 投稿モジュール
- `utils/` — ユーティリティ
- `config/` — 設定ファイル
- `docs/sessions/` — 実行ログ
- `docs/knowledges/` — 再利用可能な知見
- `docs/context/` — 背景情報・プロトコル
- `docs/adr/` — アーキテクチャ決定記録
- `.codex/skills/` — エージェントスキル定義
