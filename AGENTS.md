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

### 設計思想

**パイプライン型（工場ライン）ではなく、ディスカッション型（専門家会議）。**

リサーチャーの調査結果が全ての土台。これが弱ければ記事の信用がない。
批評家は常に否定から入る。肯定は仕事ではない。
ただし、他エージェントが合理的かつ正確な反論をすれば、批評家はそれを受け入れる。
議論は批評すべき点がなくなるまで自然に続き、自然に収束する。
何周回るかは結果であり、目的ではない。

### エージェント体制図

```
                 ┌──────────────────────────────────┐
                 │      Discussion Table（議論卓）     │
                 │                                    │
                 │  Researcher ←→ Strategist          │
                 │      ↕              ↕              │
                 │  Critic ←────→ Writer              │
                 │      ↑                             │
                 │      │  全員がResearcherの          │
                 │      │  調査結果を共有基盤とする      │
                 └──────┼─────────────────────────────┘
                        │
                 ┌──────┴──────┐
                 │ Coordinator │ ← 議論の進行役・収束判定・記録
                 └──────┬──────┘
                        │
                        ▼
                 ┌─────────────┐
                 │  User (承認)  │
                 └─────────────┘
```

### ディスカッション・プロトコル

#### Phase 1: 土台構築（Researcher主導）

Researcherがトピックを調査し、全エージェントの共有基盤を作る。
この成果物の質が記事全体の信用度の上限を決める。

```
Researcher:
  - 一次情報の収集（学術論文、公式ドキュメント、政府データ）
  - 各ソースの信用度ティア判定（Tier 1-4）
  - 主要主張の3ソース以上クロス検証
  - 検証できなかった主張の明示
  - 反論・制限事項の収集

成果物: リサーチブリーフ
  - verified_facts: [{fact, sources: [{url, tier, access_date}], confidence}]
  - unverified_claims: [{claim, reason}]
  - counterarguments: [{position, source}]
  - evidence_summary: {total_sources, tier1_count, tier2_count, tier1_2_ratio}
```

#### Phase 2: ディスカッション（全員参加）

全エージェントがリサーチブリーフを共有基盤としてディスカッションする。
Coordinatorが議論を進行し、収束を判定する。

```
Round N（Writer↔Critic 最大2ラウンド、例外時のみ3。Researcher/Strategistは必要時のみ再参加）:

  1. Strategist発言:
     「この角度で差別化すべき。理由: Researcherの調査でXが判明、
      既存記事はYの視点が欠けている」

  2. Writer発言:
     「この構成で書く。リサーチブリーフのZ事実を核に、
      図表N個、引用M個で構成」
     → ドラフト提出

  3. Critic発言（常に否定から入る）:
     「独自性: Researcherの調査によるとX事実は既にA記事でカバー済み → 弱い」
     「正確性: Researcherが未検証とした主張Yをドラフトが断定している → 問題」
     「引用: ソース3はTier3。核心主張にTier3は不十分 → 差し替え必要」
     「視覚: 図表2個。500-800字ルールに対して不足 → 追加必要」

  4. 他エージェントの反論（合理的であれば受け入れられる）:
     Researcher: 「主張Yについて追加調査。Tier1ソースを1件発見」
     Strategist: 「既存記事AはZの観点が欠如。我々の角度は有効」
     Writer: 「図表を追加し、引用をTier1-2に差し替えた改訂版を提出」

  5. Critic再評価:
     「Researcherの追加調査でY主張が検証された → 正確性の懸念解消」
     「Strategistの反論は合理的 → 独自性は認める」
     「引用差し替え確認 → 引用品質向上」
     「残課題: 結論セクションが弱い」

  → Writer↔Critic は最大2ラウンド（例外時のみ3）
  → 同一論点が2回反復したらCoordinatorが打ち切り（REVISE or REJECT）
  → Researcher/Strategistは必要時のみ再呼び出し（Tier1不足、戦略角度問題等）
  → 批評すべき点がなくなったら、Coordinatorが収束を宣言
```

#### Phase 3: スコアリング（議論の成果物から導出）

スコアは「LLMに点数をつけさせる」のではなく、
**ディスカッションの過程で蓄積されたエビデンスから導出する**。

```
Coordinatorが以下を集約してスコアリング:

客観指標（プログラム計測 — 嘘がつけない）:
  - evidence_level: Researcherのtier1_2_ratio から算出
  - citation_count: EvidenceManagerが計測した正規引用数
  - citation_format: URL+取得日の充足率
  - visual_count: RichFormatterが計測した視覚要素数
  - word_count: 文字数
  - forbidden_phrases: 禁止フレーズ数（0以外はFail）

根拠付き主観指標（ディスカッション過程から抽出）:
  - originality: Strategistの差別化根拠 + Criticの評価
  - accuracy: Researcherの検証結果 + Criticの指摘解消状況
  - readability: Criticの構成評価
  - engagement: Criticの「So what?」テスト結果

各指標の根拠（なぜその点数か）を必ず記録する。
```

#### Phase 4: 収束条件

Coordinatorが以下の条件で議論の収束を判定:

```
収束 = 以下のすべてを満たす:
  1. Criticの未解消指摘が0件
  2. 客観指標がすべてPass/A/B（Cがない）
  3. Researcherの未検証主張がドラフトに含まれていない
  4. evidence_level が B以上

収束しない場合:
  - Writer↔Criticの追加ラウンド（上限内で）
  - Researcher/Strategistの再呼び出し（必要時のみ: ソース不足、角度問題等）
  - 同一論点が2回反復したらCoordinatorが打ち切り:
    → 解決不能な論点をblocking_issuesとしてスコアに明記
    → その論点をリスクとしてSheetsに記録
```

### スコアリング基準

#### 客観スコア（計測値 — 足切りに使用）

| 指標 | A | B | C (足切り) |
|------|---|---|-----------|
| エビデンスレベル | Tier1-2率 80%+ | 60-79% | 60%未満 |
| 引用数 | 5個以上 | 3-4個 | 0-2個 |
| 引用形式 | 全数URL+日付 | 80%+ | 80%未満 |
| 視覚要素 | 5個以上 | 3-4個 | 0-2個 |
| 禁止フレーズ | 0件 | - | 1件以上=即Fail |

**客観スコアにCが1つでもあれば、総合評価はC以下。主観がどんなに良くても覆らない。**

#### 根拠付き主観スコア（ディスカッションから導出）

| 指標 | 根拠の出所 | 評価 |
|------|-----------|------|
| 独自性 | Strategistの差別化根拠 + Criticの評価 | A/B/C |
| 正確性 | Researcherの検証結果 + 未検証主張の有無 | A/B/C |
| 可読性 | Criticの構成・フロー評価 | A/B/C |
| 引き込み | Criticの「So what?」テスト + 読者離脱ポイント数 | A/B/C |

#### 総合判定

```
総合 = min(客観スコアの最低値, 主観スコアの平均)

A: 全客観指標A + 主観平均A → ユーザーに承認推奨として提示
B: 客観にCなし + 主観平均B以上 → ユーザーに提示（注意点付き）
C: 客観にCあり or 主観平均C → ユーザーに提示しない（自動却下）
```

### Criticの行動原則

1. **全ての主張を否定から入る** — 「本当にそうか？根拠は？」
2. **Researcherの調査結果と照合** — ドラフトの主張がリサーチブリーフと矛盾していないか
3. **未検証主張の断定を許さない** — Researcherが検証できなかった主張をドラフトが事実として書いていたら即指摘
4. **合理的な反論は受け入れる** — 他エージェントがエビデンス付きで反論したら、それは認める
5. **肯定はしない** — 「良い」とは言わない。「指摘すべき点がない」と言う
6. **曖昧な指摘はしない** — 「改善してください」ではなく「セクション3のX主張はTier3ソースのみ。Tier1-2に差し替えるか、主張を弱めよ」

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
- `docs/knowledge/` — 再利用可能な知見
- `docs/context/` — 背景情報・プロトコル
- `docs/adr/` — アーキテクチャ決定記録
- `.codex/skills/` — エージェントスキル定義
