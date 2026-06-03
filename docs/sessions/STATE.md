# STATE — Current Project State

> 起動時に最初に読む 1 file。 60 行未満で維持すること。 詳細履歴は JOURNAL.md
> / archive、 ランブックは subdir CLAUDE.md、 cross-session preferences は memory。
> AUTO セクションは `py scripts/_session_status.py` で再生成 — 手動編集すると
> 次回 run で上書きされる。

**Updated**: <!-- AUTO:updated -->
2026-06-03 09:25 JST
<!-- /AUTO:updated -->

## In Flight (今このセッションで進行中の作業)

- 6-02: ①generate→publish 完遂: 3 本生成 (全 B/A) → publish。 note PDRN 有料
  (n17f9115b4383)、 zenn 2 本は queue 満杯で scrap fallback
  (scraps/f06dd121ebe5dd, 809cdfe2ef2165)。 却下 2 本。
  ②**無料バズ狙い記事を市場調査ベースで追加 publish**: 「塗る針」スピキュール
  完全ガイド (¥0, n8cd1361dc883)。 PDRN/エクソソームの"次"トレンドを first-mover。
  手書き custom_post + Unsplash 画像、 ハルシ規律 (架空商品名/価格ゼロ) で執筆。
  ③**エビデンス格付け型の確かな知財記事を無料 publish** (¥0, nb563aaac6175):
  「2026バズ美容成分、効果はどこまで本当か」。 FDA 一次/査読/皮膚科医のみ引用、
  ベンダー発の未検証数値 (78%, +64.32% 等) は峻別して不採用、 anti-hype literacy
  自体を読者に渡す構成。 今日 note 3 本 (PDRN 有料 + スピキュール無料 + 格付け無料)、
  custom_post 経路は cadence cap を通らないため user 明示依頼で override
- (6-01: poster route 汎用化 `4ba5e80`。 note membership-add を selection-mode と
  根本診断、 e2e 未達 → 手動追加へ。 詳細 `publishers/CLAUDE.md`)
- (5-29: slot scheduler 平日 daytime 化 + Task Scheduler 5 タスク
  本番登録 (`ai-publish-slot-{MON..FRI}` 12:00 JST、 初回 fire 2026-06-01
  Mon) まで完遂、 commit `3b2d228`)

## Next Actions (優先度順、 各セッションで bump、 手動メンテ)

1. **note membership 手動追加 — 6-02 の PDRN 有料記事** (n17f9115b4383):
   `/notes`→記事 ⋮→「メンバーシップ特典追加・解除」→チェック→「メンバー全員に
   公開」の「追加」。 (スピキュール記事は無料なので membership 不要)。 累計 backlog も同様
2. ~~note 画像 regen (K-beauty 3 本)~~ **✅完了 (6-03)**: PDRN/シカ/トラブル別を
   kbeauty_poster preset で cover+inline 計 15 枚 ChatGPT 再生成 → edit_article
   差し替え (generated=3 uploaded=3 failed=0)。 og:image 3 本とも新規 .png に更新確認、
   全記事 paid-flow「有料エリア設定」経由で paywall 保持、 ChatGPT chat leak 0。
   スクリプト一般化: `_regen_today_note_with_chatgpt.py` に `--preset`/`--genre` flag
   + CDP モード時 brave kill skip を追加
3. **`AUTO_LAUNCH_BRAVE_CDP` opt-in 化の再検討** — publish 時 cold port を
   毎回起動するか議論 (上記 regen は手動 launch_brave_cdp.bat で対応した)

## Active Backlog (緊急度低、 観測タスク等)

- forbidden_phrases prompt 強化 (`e313a0a`) 継続効果計測 (5-28 までで 4 日連続 pass)
- K-beauty/韓国 5 連発のクロス効果計測 (5-30 経過後、 K-POP 4 世代 paid 流入率)
- ChatGPT 画像 vision-eval 詰まり (5-27 朝の調査項目、 5-28 朝も再発)
- title_fulfillment shop counter gate (`numeric_shop_listicle`) 効果計測 (次回 generate 時)
- ~~slot scheduler 初回 fire 観測~~ **✅確認済 (6-03)**: 6-01 月 fire exit 0
  (cadence cap で 3 本翌日持ち越し→6-02 手動 publish 済)、 6-02 火 exit 0 (承認済なし no-op)。
  ops-banner/cadence-cap/free-first 全発火、 配線健全

## 次回提案候補 (5-29 セキュリティ監査の積み残し、 詳細は memory `feedback_public_repo_no_pii`)

- **全9 repo の PII/機密除去は完了** (ai-article + MyHobbyCoffee/Lp/SWELL/
  slide-forge/ForWorking を filter-repo→force-push、 全 ref タグ含め 0 件検証済)
- **未修正のコード脆弱性 (PII 以外、 別 repo)** — 提案候補:
  - `waterfall-review-app`: JWT 空シークレット fallback / login brute-force /
    Aspect IDOR (HIGH)
  - `SWELL`: CORS 反射+credentials / OAuth state CSRF / JWT 空文字 fallback
  - `claude-dotfiles`: `cat *` 過剰許可 / codex-review `$TARGET` シェル注入
- **退避データの後始末** (ユーザー判断): `E:\_client_work_backup_myhobby`
  (MHC 客先資料 38 file、 NDA 対象)、 `E:\_lp_portfolio_recovered` (Lp 画像 8 枚)
- ai-article 本体のセキュリティ hardening は完了 (commit `d98fbba` ほか)

## Known Live Issues (memory または ops_incidents に正典あり、 要 verify)

- **Zenn = slow-walk publish queue** (旧"cap" は誤診断、 2026-05-28 訂正済) →
  memory `project_zenn_cap_blocked`、 詳細 `docs/knowledge/ops_incidents.md`
- **note メンバーシップ UI 漂流** — publish 後ダッシュボード手動追加が必要
- **note `_set_price` ¥300 漂流** — paid 化時の UI セレクタ揺れ
  (`2026-05_archive.md` 5-13 セクション)

## Recent Output (auto)

<!-- AUTO:recent -->
- [PDRNの科学的根拠、自宅ケア商品 (Rejuran系) と美容医療の境界、安全に始める順序を提…](https://note.com/<NOTE_USER>/n/n17f9115b4383?app_launch=false)
- [Tell HN: Meta's AI support feature allows Instag…](https://zenn.dev/kento_cell/scraps/809cdfe2ef2165)
- [Unlawful by design: Exposing the human rights co…](https://zenn.dev/kento_cell/scraps/f06dd121ebe5dd)
- [シカ (Centella Asiatica) 完全解剖: 成分構造 / ブランド別配合比 / 肌…](https://note.com/<NOTE_USER>/n/n927503f7e3a4?app_launch=false)
- [トラブル別 緊急ケア 5 ステップ + K-beauty おすすめ救急アイテム (鎮静/抗炎症/…](https://note.com/<NOTE_USER>/n/nb8a49e7d42e5?app_launch=false)
<!-- /AUTO:recent -->

## Pipeline Health (auto)

<!-- AUTO:pipeline -->
- JOURNAL.md: 154 lines (rotation at 500 via SessionStart hook)
- Zenn queue head: (skipped in quick mode — run `py scripts/_session_status.py` for full probe)
- Recent commits (last 48h):
  - 086257c fix(note): rewrite membership-add to direct /notes selection-mode flow
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
