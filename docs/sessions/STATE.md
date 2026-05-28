# STATE — Current Project State

> 起動時に最初に読む 1 file。 60 行未満で維持すること。 詳細履歴は JOURNAL.md
> / archive、 ランブックは subdir CLAUDE.md、 cross-session preferences は memory。
> AUTO セクションは `py scripts/_session_status.py` で再生成 — 手動編集すると
> 次回 run で上書きされる。

**Updated**: <!-- AUTO:updated -->
2026-05-28 13:43 JST
<!-- /AUTO:updated -->

## In Flight (今このセッションで進行中の作業)

- なし (5-28: learn→generate→publish ALL FREE、 画像 regen (poster route)、
  Zenn 技術書 push、 session context refactor (Pattern 1-5) + 最強環境
  optimization round まで完遂)

## Next Actions (優先度順、 各セッションで bump、 手動メンテ)

1. **`ChatGPTImageGenerator._build_prompt` staticmethod gotcha ドキュメント化**
   — 5-28 1st pass regen で踏んだ Python 落とし穴を docstring に追加
2. **`AUTO_LAUNCH_BRAVE_CDP` opt-in 化の再検討** — publish 時 cold port を
   毎回起動するか議論
3. **poster route 汎用化** — `chatgpt_image_batch` に `style_preset` 引数追加
   (現状 monkey-patch hack)
4. **note メンバーシップ手動追加 (累計 20 件)** — ユーザー作業、 CC は対応不可

## Active Backlog (緊急度低、 観測タスク等)

- forbidden_phrases prompt 強化 (`e313a0a`) 継続効果計測 (5-28 までで 4 日連続 pass)
- K-beauty/韓国 5 連発のクロス効果計測 (5-30 経過後、 K-POP 4 世代 paid 流入率)
- ChatGPT 画像 vision-eval 詰まり (5-27 朝の調査項目、 5-28 朝も再発)
- title_fulfillment shop counter gate (`numeric_shop_listicle`) 効果計測 (次回 generate 時)

## Known Live Issues (memory または ops_incidents に正典あり、 要 verify)

- **Zenn = slow-walk publish queue** (旧"cap" は誤診断、 2026-05-28 訂正済) →
  memory `project_zenn_cap_blocked`、 詳細 `docs/knowledge/ops_incidents.md`
- **note メンバーシップ UI 漂流** — publish 後ダッシュボード手動追加が必要
- **note `_set_price` ¥300 漂流** — paid 化時の UI セレクタ揺れ
  (`2026-05_archive.md` 5-13 セクション)

## Recent Output (auto)

<!-- AUTO:recent -->
- [Tech CEOs are apparently suffering from AI psych…](https://note.com/note-user/n/nfd797bf2135d?app_launch=false)
- [1週間で持ち物を1-2割減らせる 丁寧な減らし方 プログラム。7日×30分で、捨てる/譲る/売る…](https://note.com/note-user/n/ne0959d6ff8f7?app_launch=false)
- [韓国コスメ起因の肌トラブル 5 パターン (接触皮膚炎/光毒性/酸不耐症/エクソソーム反応/偽物…](https://note.com/note-user/n/nd5cd08163f15?app_launch=false)
- [日本で韓国コスメを買える 4 経路 (OliveYoung実店舗 / @cosme TOKYO韓…](https://note.com/note-user/n/n46ccc31f4994?app_launch=false)
- [【保存版】「新大久保以外」で韓国カフェの本物に出会う —— 都内 6 軒、エリア別に実名で…](https://note.com/note-user/n/n40b6f0a288b8?app_launch=false)
<!-- /AUTO:recent -->

## Pipeline Health (auto)

<!-- AUTO:pipeline -->
- JOURNAL.md: 87 lines (rotation at 500 via SessionStart hook)
- Zenn queue head: (skipped in quick mode — run `py scripts/_session_status.py` for full probe)
- Recent commits (last 48h):
  - f95b269 fix(context): redirect stale LATEST.md refs to STATE/JOURNAL after split
  - 785a540 docs(context): split LATEST.md → STATE/JOURNAL/archive + subdir CLAUDE.md (-91% cold-start tokens)
  - e9bf8d0 chore(scripts,learn): 5-28 one-shots — ChatGPT regen with poster route + Zenn prompt-book push + auto-learn snapshot
  - 150499d feat(scorer): title_fulfillment shop counter gate (kc_002 regression)
  - 5e15b6a feat(policy): borrowed-image free-only guard + Korean cafe article rewrite
<!-- /AUTO:pipeline -->

## Pointers

- 今日の詳細ログ → `docs/sessions/JOURNAL.md`
- 過去の session 履歴 → `docs/sessions/2026-05_archive.md` (旧 LATEST.md、 5-14 から 5-28 朝まで)
- 古い設計判断 (4-7/4-29/5-11) → `docs/sessions/archive/_legacy/`
- Compound Workflow + Scripts カタログ → `scripts/CLAUDE.md` (path-scoped lazy load)
- publish 罠 → `publishers/CLAUDE.md`
- Slack bot コマンド → `bot/CLAUDE.md`
- cross-session preferences → `~/.claude/projects/E--ai-article-auto-publisher/memory/MEMORY.md`
- session-reader subagent: `Agent(subagent_type="session-reader")` で履歴を Haiku 圧縮
