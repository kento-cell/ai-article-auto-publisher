# Agent Operating Guide

## Purpose

AI記事自動生成・投稿システムのエージェント運用ガイド。
5つの専門エージェントが協調して、収集→調査→戦略→執筆→批評→投稿のパイプラインを運用する。

## Entry Workflow

1. Read `docs/sessions/LATEST.md` first for immediate context recovery.
2. If `LATEST.md` is missing or stale, read the newest `docs/sessions/YYYYMMDD_*.md` file.
3. Read `config/settings.yaml` for current system configuration.
4. Read `AI_CONTEXT.md` for repository structure understanding.

## Local Skill Set

スキル定義は2箇所に配置（内容は同一）:
- **`.claude/skills/`** — Claude Code (cc) 用（プライマリ）
- **`.codex/skills/`** — Codex CLI 互換エイリアス

### スキル一覧

| Skill | Claude Code | Codex CLI | Role |
|-------|------------|-----------|------|
| core | `.claude/skills/core/SKILL.md` | `.codex/skills/core/SKILL.md` | コンテキスト復元・基本行動 |
| collection | `.claude/skills/collection/SKILL.md` | `.codex/skills/collection/SKILL.md` | 記事収集・トレンド分析 |
| generation | `.claude/skills/generation/SKILL.md` | `.codex/skills/generation/SKILL.md` | 記事生成・LLM連携 |
| quality-gate | `.claude/skills/quality-gate/SKILL.md` | `.codex/skills/quality-gate/SKILL.md` | 品質評価・エビデンス検証 |
| publishing | `.claude/skills/publishing/SKILL.md` | `.codex/skills/publishing/SKILL.md` | 投稿・通知 |
| self-improvement | `.claude/skills/self-improvement/SKILL.md` | `.codex/skills/self-improvement/SKILL.md` | 振り返り・学習 |

### エージェント役割スキル

| Agent Role | Claude Code | Codex CLI | 責務 |
|------------|------------|-----------|------|
| researcher | `.claude/skills/researcher/SKILL.md` | `.codex/skills/researcher/SKILL.md` | 深掘り調査・ファクトチェック・ソース信用度評価 |
| strategist | `.claude/skills/strategist/SKILL.md` | `.codex/skills/strategist/SKILL.md` | トピック選定・差別化角度・コンテンツ戦略 |
| writer | `.claude/skills/writer/SKILL.md` | `.codex/skills/writer/SKILL.md` | 執筆・リッチテキスト・画像配置・視覚設計 |
| critic | `.claude/skills/critic/SKILL.md` | `.codex/skills/critic/SKILL.md` | 品質批評・読者目線レビュー・改善指摘 |
| coordinator | `.claude/skills/coordinator/SKILL.md` | `.codex/skills/coordinator/SKILL.md` | 全体統括・ハンドオフ管理・最終品質保証 |

スキルを更新する場合は両方のパスを同期すること。

## Multi-Agent Architecture

### エージェント体制図

```
                    ┌─────────────┐
                    │ Coordinator │ ← 全体統括・ハンドオフ管理
                    │  (まとめ役)  │
                    └──────┬──────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Researcher  │  │  Strategist  │  │    Critic    │
│ (リサーチャー) │  │  (戦略家)    │  │  (批評家)    │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └────────┐  ┌─────┘                 │
                ▼  ▼                       │
           ┌──────────┐                    │
           │  Writer  │ ←── 批評フィードバック ──┘
           │ (ライター) │
           └──────────┘
```

### エージェント間ハンドオフ・プロトコル

```
1. Collection → Coordinator: ランク付き記事リスト
2. Coordinator → Researcher: トピック + 初期ソース
3. Researcher → Coordinator: リサーチブリーフ（検証済み事実 + ソース信用度）
4. Coordinator → Strategist: リサーチブリーフ + トレンドデータ
5. Strategist → Coordinator: 戦略ブリーフ（角度・ペルソナ・構成）or REJECT
6. Coordinator → Writer: リサーチブリーフ + 戦略ブリーフ
7. Writer → Coordinator: 記事ドラフト（リッチテキスト + 画像 + 図表）
8. Coordinator → Critic: 記事ドラフト + 戦略ブリーフ
9. Critic → Coordinator: レビュー（APPROVE / REVISE / REJECT）
10. [REVISE] Coordinator → Writer: フィードバック付き再執筆指示（最大2回）
11. [APPROVE] Coordinator → User: 承認待ちキュー
12. User → Coordinator: 投稿承認
13. Coordinator → Publisher: 確定記事
```

### 品質評価基準（7軸 / 70点満点）

| 軸 | 評価内容 | 配点 |
|----|---------|------|
| Originality（独自性） | 翻訳以上の価値、独自視点 | 0-10 |
| Accuracy（正確性） | 事実の正しさ、コードの動作 | 0-10 |
| Readability（可読性） | 構成、フロー、スキャンしやすさ | 0-10 |
| Citation（引用） | 出典明記、Tier 1-2ソース | 0-10 |
| Practicality（実用性） | 読者が実践できるか | 0-10 |
| Visual Appeal（視覚性） | 画像・図表の量と質、視覚的余白 | 0-10 |
| Engagement（引き込み） | 最後まで読ませる力 | 0-10 |

判定基準:
- **60+/70: APPROVE** → 投稿承認キューへ
- **45-59/70: REVISE** → Writer に具体的フィードバック付きで差し戻し
- **<45/70: REJECT** → Strategist に差し戻し or トピック破棄

### ソース信用度ティア

| Tier | 信用度 | ソース例 |
|------|--------|---------|
| Tier 1 | 最高 | 学術論文、公式ドキュメント、政府データ |
| Tier 2 | 高い | 大手テックブログ（Google, Anthropic, OpenAI）、主要メディア |
| Tier 3 | 補助的 | コミュニティ投稿（Reddit, HN）、個人ブログ |
| Tier 4 | 使用回避 | 匿名ソース、未検証の主張 |

ルール: 記事の核となる主張には必ずTier 1-2のソースを3つ以上使用すること。

## Pipeline Workflow

```
[Collection] → [Coordinator] → [Researcher] → [Strategist] → [Writer] → [Critic]
                    ↑              ↑                              │          │
                    │              │         feedback loop         │          │
                    │              └──────────────────────────────┘          │
                    │                                                        │
                    ├──── APPROVE → [Human Review] → [Publishing]           │
                    │                                                        │
                    └──── self-improvement (learning) ──────────────────────┘
```

### Phase 1: Collection（収集）
- Trigger: 毎日22:00 または手動実行
- Skill: `collection`
- Agent: N/A（自動処理）
- Input: ソース設定 (settings.yaml)
- Output: ランク付きトレンド記事リスト

### Phase 2: Research（調査）
- Trigger: Coordinatorからの指示
- Skill: `researcher`
- Agent: **Researcher**
- Input: トピック + 初期ソース
- Output: リサーチブリーフ（検証済み事実、ソース信用度ティア、反論・制限事項）

### Phase 3: Strategy（戦略立案）
- Trigger: リサーチブリーフ受領後
- Skill: `strategist`
- Agent: **Strategist**
- Input: リサーチブリーフ + トレンドデータ
- Output: 戦略ブリーフ（差別化角度、ターゲットペルソナ、構成、価格推奨）
- 差別化不可 → トピック破棄

### Phase 4: Writing（執筆）
- Trigger: 戦略ブリーフ受領後
- Skill: `writer`
- Agent: **Writer**
- Input: リサーチブリーフ + 戦略ブリーフ
- Output: リッチテキスト記事（画像・図表・コールアウト・引用付き）

### Phase 5: Critique（批評）
- Trigger: ドラフト完成後
- Skill: `critic`
- Agent: **Critic**
- Input: 記事ドラフト + 戦略ブリーフ
- Output: 7軸レ���ュー（APPROVE / REVISE / REJECT）
- REVISE → Writer に差し戻し（最大2回）

### Phase 6: Human Review（人間承認）
- Trigger: Critic APPROVE後
- Agent: **Coordinator** → ユーザー
- Input: 承認済み記事
- Output: 投稿承認 or 却下

### Phase 7: Publishing（投稿）
- Trigger: ユーザー承認後
- Skill: `publishing`
- Agent: N/A（自動処理）
- Input: 確定記事
- Output: 投稿URL + Slack通知

## Image & Visual Rules

### 著作権安全設計

全画像は以下のいずれかに該当すること:
- **CC0 / パブリックドメイン**: Unsplash, Pexels 等
- **AI生成画像**: DALL-E, Stable Diffusion, SVGプレースホルダー
- **自作図表**: Mermaid記法、独自SVG
- **スクリーンショット**: 検証記事用、フェアユース範囲

### 画像ルール

1. 全画像に出典・ライセンスを明記（CC0でも帰属表示を付��る）
2. ホットリンク禁止（ダウンロードしてローカル/リポジトリに配置）
3. 全画像にalt textを付与
4. ホットリンク先が消えても記事が成立するようにキャプションで補完

### ビジュアル密度ターゲット

- 記事あたり最低3つの視覚要素（画像/図表/テーブル）
- 500-800文字ごとに視覚的ブレイクを配置
- ヒーロー画像を記事冒頭に配置
- セクション間に画像またはフローを挿入

### リッチテキスト要件

| 要素 | Zenn記法 | note記法 | 最低数 |
|------|---------|---------|--------|
| コールアウト | `:::message` | `> **💡**` | 2個/記事 |
| トグル | `:::details` | `<details>` | 長コード用 |
| テーブル | Markdown table | Markdown table | 1個/記事 |
| Mermaid図 | ` ```mermaid` | 画像化して挿入 | 1個/技術記事 |
| コードブロック | ` ```lang` | ` ```lang` | 1個/技術記事 |
| 太字強調 | `**text**` | `**text**` | 重要用語の初出時 |

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
