# Latest Session

## Current Topic

ai-article-auto-publisher — 2026-05-13 セッション。compound publish flow
完走 (generate → bulk approve → free+paid mix → scrap → ChatGPT 画像 regen) +
他セッション portability のための CLAUDE.md playbook 整備。

## Current Status

- **Phase**: 量産運用期。1 日 8 本 publish + 10 scrap + 4 本画像 regen が
  1 セッションで完走するレベルに整備済み。
- **Pipeline 健全性**: note 投稿 healthy、Zenn は cap で article publish 不可 →
  scrap fallback で迂回中。
- **Recent commits** (push 待ち):
  - `cecf594` chore(scripts): one-shot operational utilities
  - `864c47c` docs(knowledge): auto-learning snapshots
  - `83a1d92` feat(images): per-image fresh chat + game-homage + CDP attach
  - `6584cb6` fix(quality): masked-name + AI-disclosure deny patterns
  - `329a81d` fix(zenn): cap-detection pre-flight + bulk publish helper
  - `0dfe940` fix(images): security + divergence-prevention pass

## 今日 (2026-05-13) の成果

1. **generate**: 1 件採用 / 6 件却下 (CのリーダビリティC/アキュラシーCなど)
2. **bulk approve**: 5 行 (note×4 + zenn×1)
3. **publish**: note 4 本 (¥0×2 + ¥300×2) + zenn 4 本 (cap fallback → scrap)
4. **scrap 追加投稿**: 10 本 (未投稿ドラフトから) ※3 本タイトルが「参考文献」になる不具合 → スクリプト修正済 (`_extract_title` 改善)
5. **ChatGPT 画像 regen**: 4 本の note 全部 cover+inline 差し替え (Bug 3 false-neg 2 件あり、og:image 更新で実証済 → 実態 4/4 success)
6. **新スクリプト 4 本追加**: `_publish_free_first.py` / `_publish_pending_scraps.py` / `_regen_today_note_with_chatgpt.py` / `launch_brave_cdp.bat`
7. **CDP attach モード活性化**: `.env` に `CHATGPT_CDP_PORT=9222` 追加、Brave 起動中でも ChatGPT 画像生成可能に
8. **CLAUDE.md playbook 追加**: 「ジェネレートして承認してパブリッシュ」「無料 N+有料 M」「画像 regen」を他セッションでも同じに再現できる手順表

## Open Items

1. **Zenn article cap** — ユーザーがダッシュボード確認するまで article publish 控える
2. **AI 開示 footer 26 件の修復** — `scripts/strip_ai_disclaimer_from_published.py --apply` 未実行 (1-2 時間枠が必要)
3. **Places API キー貼付待ち** — 本人作業のみ
4. **アフィリ広告主 ASP 申請 15 件待ち** — 本人作業のみ
5. **note 4 本のメンバーシップ追加** — `_add_to_memberships_via_dashboard` がボタン取得失敗で skip。ダッシュボードから手動追加が必要 (URL ↓)
   - https://note.com/note-user/n/nebdb6edacb1e
   - https://note.com/note-user/n/n5a0a2ad50965
   - https://note.com/note-user/n/n536e614dc601
   - https://note.com/note-user/n/nd5812c715125
6. **「参考文献」タイトルの Zenn scrap 3 本** — タイトル間違いで投稿された。Zenn UI で手動編集 or 削除
   - https://zenn.dev/zenn-user/scraps/d304dfc7fc6c16
   - https://zenn.dev/zenn-user/scraps/2e6a66de165713
   - https://zenn.dev/zenn-user/scraps/ea17391664fcf8

## Next Resume Actions（自走で実行すること）

### 1. 起動時デグレチェック

```bash
py -c "import main"
py scripts/test_hallucination_deny.py
```

### 2. ユーザー指示の正規化マッピング

CLAUDE.md の **Compound Workflow Playbook** セクションを参照。よく来る指示:

- 「ジェネレートして全部承認してパブリッシュ」 → `main.py --generate` → `_bulk_approve_sheet.py` → `_publish_free_first.py --free-first 0`
- 「無料 N 本 + 有料 M 本」 → `_publish_free_first.py --free-first N`
- 「スクラップ記事投稿」 → `_publish_pending_scraps.py --limit 10`
- 「画像 ChatGPT で差し替え」 → Brave 終了 (or CDP) → regen スクリプト

### 3. push 待ち commit を origin に反映

`git push` (ユーザー指示があれば)。今は手元に 7 本 commit 積み上げ済み。

## Key Documents

| ファイル | 内容 |
|---------|------|
| **CLAUDE.md** | セットアップ、デグレチェック、**Compound Workflow Playbook**、Scripts カタログ |
| AGENTS.md | ディスカッション型アーキテクチャ、スコアリング基準 |
| docs/requirements.md | 要件定義 v1.1 |
| docs/knowledge/hallucination_registry.md | ハルシネーション事故レジストリ (canonical) |
| docs/knowledge/quality_insights_2026-05-09.md | 最新のエンゲージメント学習スナップショット |
| config/prompts.yaml | プロンプト (理念、構成パターン、禁止ルール) |
| config/settings.yaml.example | 48 forbidden_phrases、伏字+業態語、AI 開示 footer 等 |

## Updated At

2026-05-13 09:30 JST
