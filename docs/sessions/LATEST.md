# Latest Session

## Current Topic

ai-article-auto-publisher — 品質防衛 (hallucination registry) + ChatGPT 画像パイプライン拡張
が一通り landing。Zenn cap ブロック中で article publish は控え中。

## Current Status

- **Phase**: 品質パターン蓄積期。エンゲージメント自動学習 → deny pattern 拡充 → 再投稿のループ
- **Pipeline**: Zenn article publish は 4-15 以降 silently 404 (cap 疑い)。
  scrap fallback + bulk publish helper で回避中。note は健全。
- **Recent commits** (5-11 push 待ち含む):
  - `aa86c87` chore(scripts): one-shot operational utilities
  - `864c47c` docs(knowledge): 2026-04-30 + 2026-05-09 auto-learning snapshots
  - `83a1d92` feat(images): per-image fresh chat + game-homage style pack + CDP attach
  - `6584cb6` fix(quality): masked-name + AI-disclosure deny patterns + length retune
  - `329a81d` fix(zenn): cap-detection pre-flight + bulk publish helper
  - `0dfe940` fix(images): security + divergence-prevention pass (Codex cross-review)

## Open Items (memory より引き継ぎ)

1. **Zenn article cap** — ユーザーがダッシュボード確認するまで article publish 控える
2. **AI 開示 footer 26 件の修復実行** — `scripts/strip_ai_disclaimer_from_published.py --apply`
   未実行。Brave + NotePublisher で 1-2 時間の安定実行時間が必要なのでユーザー承認待ち
3. **Places API キー貼付待ち** — コード完了、本人作業のみ
4. **アフィリ広告主 ASP 申請 15 件待ち** — 本人作業のみ

## Next Resume Actions（自走で実行すること）

### 1. 起動時デグレチェック

```bash
py -c "import main"
py scripts/test_hallucination_deny.py  # 40 deny + 7 sanitizer
```

### 2. Open Items の進行状況をユーザーに確認

承認 + Zenn cap 状況確認が要なので、ユーザー到着時に状況を聞く。

### 3. 必要に応じて E2E テスト

```bash
py main.py --collect-only
py main.py --dry-run
py main.py --generate
```

### 4. push 待ち commit を origin に反映

`git push` (ユーザー指示があれば)。今は手元に 4 commits 積み上げ済み。

## Key Documents

| ファイル | 内容 |
|---------|------|
| CLAUDE.md | セットアップ、デグレチェック、日常運用 |
| AGENTS.md | ディスカッション型アーキテクチャ、スコアリング基準 |
| docs/requirements.md | 要件定義 v1.1 |
| docs/knowledge/hallucination_registry.md | **ハルシネーション事故レジストリ (canonical)** |
| docs/knowledge/quality_insights_2026-05-09.md | 最新のエンゲージメント学習スナップショット |
| docs/sessions/20260407_codex_consultation.md | Codex 設計合意 |
| docs/sessions/20260407_monetization_research.md | マネタイズ戦略 |
| config/prompts.yaml | プロンプト (理念、構成パターン、禁止ルール) |
| config/settings.yaml.example | 48 forbidden_phrases、伏字+業態語、AI 開示 footer 等 |

## Updated At

2026-05-11 JST
