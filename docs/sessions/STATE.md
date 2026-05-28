# STATE — Current Project State

> 起動時に最初に読む 1 file。 60 行未満で維持すること。 詳細履歴は JOURNAL.md
> / archive、 ランブックは `.claude/rules/`、 cross-session preferences は memory。

**Updated**: 2026-05-28 13:10 JST | **Today's session log**: `docs/sessions/JOURNAL.md`

## In Flight (今このセッションで進行中の作業)

- なし (5-28 朝の learn→generate→publish ALL FREE / 画像 regen / Zenn 技術書 push / **session context リファクタ (Pattern 1-5 全実装)** まで完遂)

## Next Actions (優先度順、 各セッションで bump)

1. **コミット 5-28 全変更** — Zenn / regen / context リファクタ (root CLAUDE.md trim、 STATE/JOURNAL/archive 分離、 publishers|scripts|bot/CLAUDE.md 新規、 session-reader subagent、 SessionStart hook、 memory 訂正、 _publish_prompt_book_to_zenn.py、 _regen_5_28_*.py)
2. **note メンバーシップ手動追加 (累計 20 件)** — ユーザー作業、 CC は対応不可
3. **`ChatGPTImageGenerator._build_prompt` staticmethod gotcha ドキュメント化** — 1st pass regen で踏んだ Python 落とし穴を generators/chatgpt_image_generator.py の docstring に追加
4. **`AUTO_LAUNCH_BRAVE_CDP` opt-in 化の再検討** — publish 時 cold だった port を毎回起動するか議論
5. **poster route 汎用化** — `chatgpt_image_batch` に `style_preset` 引数追加 (現状 monkey-patch hack)

## Active Backlog (緊急度低、 5-30 経過後の観測タスク等)

- forbidden_phrases prompt 強化 (`e313a0a`) 継続効果計測 (5-28 までで 4 日連続 pass)
- K-beauty/韓国 5 連発のクロス効果計測 (5-30 経過後、 K-POP 4 世代 paid 流入率)
- ChatGPT 画像 vision-eval 詰まり (5-27 朝の調査項目、 5-28 朝も再発)
- title_fulfillment shop counter gate (`numeric_shop_listicle`) 効果計測 (次回 generate 時)

## Known Live Issues (memory または ops_incidents に正典あり、要 verify)

- **Zenn = slow-walk publish queue** (旧"cap" は誤診断、 2026-05-28 訂正済) →
  memory `project_zenn_cap_blocked`、 詳細 `docs/knowledge/ops_incidents.md`
- **note メンバーシップ UI 漂流** — publish 後ダッシュボード手動追加が必要
- **note `_set_price` ¥300 漂流** — paid 化時の UI セレクタ揺れ (LATEST archive 5-13)

## Recent Output (last publish round)

- **5-28 note 4 free**: kc_004 / sl_003 / kb_007 / Tech CEOs → 4 件全 ChatGPT 画像差し替え済
- **5-28 Zenn push**: `20260528-prompt-engineering-2026-3models` (queue 待ち、 30-90 日後公開)

## Pointers

- 今日の詳細ログ → `docs/sessions/JOURNAL.md`
- 過去の session 履歴 → `docs/sessions/2026-05_archive.md` (旧 LATEST.md、 5-14 から 5-28 朝まで)
- Compound Workflows / Scripts カタログ → `.claude/rules/workflows.md` / `scripts-catalog.md`
- 既知の publish 罠 → `.claude/rules/publish-pitfalls.md`
- cross-session preferences → `~/.claude/projects/E--ai-article-auto-publisher/memory/MEMORY.md`
