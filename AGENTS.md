# Agent Operating Guide

## Purpose

AI 記事自動生成・投稿システムのエージェント運用ガイド。 5 つの専門エージェント
(Researcher / Strategist / Writer / Critic / Coordinator) が **ディスカッション
型** で協調して、 収集→調査→戦略→執筆→批評→投稿のパイプラインを運用する。

このファイルは **Codex CLI 等の非 Claude エージェント** からも読まれる共通
ガイド (Claude Code の root CLAUDE.md と相補)。 重複は避けて、 各々の正典を参照。

## Entry Workflow

(2026-05-28 改訂 — context refactor、 cold-start 76K→6.8K tok 削減)

1. Read `docs/sessions/STATE.md` (≤60 行、 current state + Next Actions)
2. 詳細履歴は `docs/sessions/JOURNAL.md` (今日) or
   `docs/sessions/2026-05_archive.md` (past sessions、 必要時のみ)、
   もしくは `Agent(subagent_type="session-reader")` で Haiku に圧縮
3. Read `config/settings.yaml` for current system configuration (必要時)

## Local Skill Set

スキル定義は 2 箇所に同期配置:
- **`.claude/skills/`** — Claude Code 用 (プライマリ)
- **`.codex/skills/`** — Codex CLI 互換ミラー (更新時は両方同期必須)

詳細は `.claude/skills/*/SKILL.md` を直接参照 (パイプラインスキル: core,
collection, generation, quality-gate, publishing, self-improvement / エージェント
ロールスキル: researcher, strategist, writer, critic, coordinator)。

## Multi-Agent Architecture

### 設計思想

**パイプライン型 (工場ライン) ではなく、 ディスカッション型 (専門家会議)。**

- リサーチャーの調査結果が全ての土台。 これが弱ければ記事の信用がない
- 批評家は常に否定から入る。 肯定は仕事ではない
- ただし、 他エージェントが合理的かつ正確な反論をすれば、 批評家はそれを受け入れる
- 議論は批評すべき点がなくなるまで自然に続き、 自然に収束する
- 何周回るかは結果であり、 目的ではない

### エージェント体制図

```
            ┌──────────────────────────────────┐
            │      Discussion Table (議論卓)    │
            │  Researcher ←→ Strategist         │
            │      ↕              ↕              │
            │  Critic ←────→ Writer              │
            │      ↑                             │
            │      │  全員が Researcher の        │
            │      │  調査結果を共有基盤とする      │
            └──────┼─────────────────────────────┘
                   │
            ┌──────┴──────┐
            │ Coordinator │ ← 議論の進行役・収束判定・記録
            └──────┬──────┘
                   ▼
            ┌─────────────┐
            │  User (承認)  │
            └─────────────┘
```

### ディスカッション・プロトコル

**Phase 1 (Researcher 主導)**: 一次情報収集 → リサーチブリーフ作成
(verified_facts / unverified_claims / counterarguments / evidence_summary)。
この成果物の質が記事全体の信用度の上限を決める。

**Phase 2 (全員参加)**: Strategist が差別化角度、 Writer がドラフト、
Critic が否定指摘、 各エージェントが合理的反論。 Writer↔Critic 最大 2
ラウンド (例外時のみ 3)、 同一論点 2 回反復で Coordinator が REVISE/REJECT
打ち切り。 Researcher/Strategist は Tier1 不足や戦略角度問題等の必要時のみ
再呼び出し。

**Phase 3 (スコアリング)**: 議論の過程で蓄積されたエビデンスから導出
(LLM に点数をつけさせるのではない)。 Coordinator が客観 + 根拠付き主観を集約。

**Phase 4 (収束条件)**: Critic 未解消 0 件 + 客観全て Pass/A/B + 未検証主張
不含 + evidence_level B 以上、 全て満たせば収束。

### スコアリング基準

| 客観指標 | A | B | C (足切り) |
|---|---|---|---|
| エビデンス Tier1-2 率 | 80%+ | 60-79% | <60% |
| 引用数 | 5+ | 3-4 | 0-2 |
| 引用形式 (URL+日付) | 全数 | 80%+ | <80% |
| 視覚要素 | 5+ | 3-4 | 0-2 |
| 禁止フレーズ | 0 | - | 1+ = 即 Fail |

**客観に C が 1 つでもあれば総合 C → 自動却下** (主観がどんなに良くても覆らない)。

主観 (議論から導出): 独自性 (Strategist 差別化根拠 + Critic 評価) / 正確性
(Researcher 検証 + 未検証主張有無) / 可読性 (Critic 構成評価) / 引き込み
(Critic So-what テスト) → 各 A/B/C。

総合 = `min(客観最低値, 主観平均)`。

### Critic の行動原則

1. 全主張を否定から入る (「本当にそうか？ 根拠は？」)
2. Researcher の調査結果と照合 (矛盾なら指摘)
3. 未検証主張の断定を許さない
4. 合理的反論 (エビデンス付き) は受け入れる
5. 肯定はしない — 「指摘すべき点がない」 と言う
6. 曖昧な指摘はしない (具体的に「セクション 3 の X 主張は Tier3 のみ。 差し替えよ」)

### ソース信用度ティア

| Tier | 信用度 | 例 |
|---|---|---|
| 1 | 最高 | 学術論文、 公式ドキュメント、 政府データ |
| 2 | 高い | 大手テックブログ (Google / Anthropic / OpenAI)、 主要メディア |
| 3 | 補助的 | Reddit / HN、 個人ブログ |
| 4 | 使用回避 | 匿名ソース、 未検証主張 |

ルール: 記事の核となる主張には必ず Tier 1-2 のソースを 3 つ以上使用。

## Pipeline Phase Summary

```
[Collection] → [Coordinator] → [Researcher] → [Strategist] → [Writer] → [Critic]
                    ↑              ↑                              │          │
                    │              └─── feedback loop ─────────────          │
                    │                                                        │
                    ├──── APPROVE → [Human Review] → [Publishing]           │
                    │                                                        │
                    └──── self-improvement (learning) ──────────────────────┘
```

詳細フェーズ運用 (Trigger / Skill / Input / Output) は
`.claude/skills/{collection,researcher,strategist,writer,critic,coordinator,publishing}/SKILL.md` を参照。

## Image & Visual Rules

詳細は `publishers/CLAUDE.md` (借用画像の paid 化禁止 / note CDN re-host
必須) + memory `feedback_inline_image_style` `feedback_thumbnail_style_preference`
を参照。 基本ルール:

- 全画像に出典・ライセンス明記、 ホットリンク禁止、 alt text 必須
- stock (CC0 / Unsplash / Pexels / AI 生成) は paid 可、 借用 (公式 SNS 等) は free 限定
- ビジュアル密度: 記事あたり最低 3 要素、 500-800 字ごとに視覚ブレイク

## Operating Rules

- パイプラインの各フェーズは独立実行可能、 エラーで停止せずスキップ
- トークン予算 (週次 2M、 警告 80%、 超過時 Ollama fallback) を常に確認
- 禁止フレーズ (`config/settings.yaml` 参照) を含む記事は自動除外
- 引用・出典のない主張を含む記事は投稿しない

## Memory Recovery Rules

- Primary: `docs/sessions/STATE.md` (60 行未満、 current state + Next Actions)
- 詳細: `docs/sessions/JOURNAL.md` (今日) / `docs/sessions/2026-05_archive.md` (履歴)
- Cross-session preferences: `~/.claude/projects/.../memory/` (Claude only)
  → Codex は同等の永続レイヤを持たないため、 重要な user preference は
  必要に応じて本ファイルか `docs/sessions/STATE.md` に明記

## Auto Logging Rules

- High-signal events を log:
  - パイプライン実行結果 (成功/失敗、 件数)
  - 品質評価で不合格になったパターン
  - トークン消費異常 (急増、 予算超過)
  - 新トレンドトピックの出現
  - 投稿エラー (UI 変更等)
- Log は `docs/sessions/JOURNAL.md` に append
- セッション切替時は `STATE.md` の Next Actions と In Flight を bump

## 関連ドキュメント (重複は排除済)

- **Compound Workflow Playbook + Scripts カタログ** → `scripts/CLAUDE.md`
  (scripts/ を触った時のみ lazy load)
- **publish 罠** (Zenn slow-walk / note _set_price / membership UI 漂流 /
  edit_article false-negative / 借用画像) → `publishers/CLAUDE.md`
- **Slack Bot コマンド** → `bot/CLAUDE.md`
- **理念 + デグレチェック + アーキテクチャ** → root `CLAUDE.md`
- **既知ハルシ事故レジストリ** → `docs/knowledge/hallucination_registry.md`
- **運用 SOP + ops_incidents** → `docs/knowledge/operations.md` /
  `docs/knowledge/ops_incidents.md`
