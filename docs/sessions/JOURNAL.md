# JOURNAL — Append-Only Session Log

> Append today's session work here. Auto-rotated to
> `docs/sessions/archive/YYYY-MM-JOURNAL.md` by SessionStart hook when
> line count exceeds 500. Past months live in `archive/`. **This file
> is NOT auto-read on startup** — use STATE.md for current state,
> Read this only when you need decision provenance.

## 2026-05-28

### Morning (07:21 – 08:32)

- **learn**: 280 samples / joined 129/157 (82%) / RAG 506 chunks / past_articles 384 → snapshots `quality_insights_2026-05-28.md`
- **generate**: 5 pass (all note, rows 105-109) / 2 reject (zenn forbidden_phrases + citation 0). 新 shop counter gate (numeric_shop_listicle) trigger 観測なし (collection に「N軒」型 nil)
- **bulk_approve + publish ALL FREE (--free-first 999)**:
  - row 105 (Claude Code 月10万円) → **deny-pattern hit** で publish 直前 reject、 Sheets 自動 ❌却下 (publish 経路の hallucination guard 機能実証)
  - row 106 韓国コスメ 4 経路 (kc_004): https://note.com/note-user/n/n46ccc31f4994
  - row 107 sl_003 持ち物減: https://note.com/note-user/n/ne0959d6ff8f7
  - row 108 kb_007 肌トラブル: https://note.com/note-user/n/nd5cd08163f15
  - row 109 Tech CEOs: https://note.com/note-user/n/nfd797bf2135d
- ChatGPT 画像 batch 全 4 件 fail (CDP 未起動 + launch_persistent_context exitCode=21)、 Unsplash fallback

### Late morning (10:00 – 11:06) — ChatGPT 画像 regen with poster route

新規 `scripts/_regen_5_28_note_images.py` + `scripts/_regen_5_28_standard_only.py`:
- K-beauty 2 (kc_004 / kb_007) → **poster route** (`_poster_build_prompt` で `ChatGPTImageGenerator._build_prompt` を monkey-patch、 cover の infographic 強制テンプレを bypass して実写エディトリアル雑誌調生成)
- 標準 2 (sl_003 / Tech CEOs) → 既存 chatgpt_image_batch
- 1st pass で **staticmethod descriptor gotcha** 踏む (`original_build = cls._build_prompt` で unwrap → 復元時 instance method 化 → `self` が第1 positional として渡って `is_cover` 衝突)
- 修正: `cls.__dict__["_build_prompt"]` で descriptor object 取得して復元
- 2nd pass で残り 2 件成功、 4/4 全件画像差し替え完了
- ChatGPT sidebar sweep: deletable 0 (per-image policy で逐次 soft-delete 済)

### Afternoon (11:15 – 11:35) — Zenn cap re-diagnose + 技術書 push

ユーザー指示「zenn が停滞？ してるなら必ず投稿、 技術書を、 スクラップではなく記事」 → 二重問題判明:

1. **旧 memory「Zenn cap 原因未解明」 は誤診断** (27 日生存):
   - Zenn API で確認 → 最新公開は今日 11:25 JST に slug `20260417-rad-2` = **6 週間遅延**
   - 1 article / 2-3 日ペースで slow-walk publish queue 処理中
   - スパム化リスク無し、 既存 push 済みは順次公開
2. **ローカル push 失敗** (5-19 以降 8 commit):
   - `E:/zenn-content` の `branch.main.upstream` 未設定
   - `git push` (no args) が「no upstream configured」 で失敗、 publisher は CalledProcessError catch して False 返すのみ
   - 5-19 以降 8 commit が origin/main に届かずローカル堆積
   - 修正: `git push --set-upstream origin main` 1 発で 8 commit + 今日の technical book を push

新規 `scripts/_publish_prompt_book_to_zenn.py`:
- `scripts/_prompt_engineering_book.md` (1357 行 / 54KB) を Zenn frontmatter 被せて変換
- slug `20260528-prompt-engineering-2026-3models`、 published: true
- push 成功 (`Bypassed rule violations for refs/heads/main`)
- URL (公開後): https://zenn.dev/zenn-user/articles/20260528-prompt-engineering-2026-3models
- 現在 curl 404 = queue 投入済、 actual 公開は 30-90 日後

memory `project_zenn_cap_blocked` を「slow-walk queue」 に書き換え、 MEMORY.md 索引も更新。

### Afternoon (11:35–) — LATEST.md 肥大化対策 (このリファクタ)

ユーザー指示「肥大化して CC 起動するたびに容量食うなら NG。 いい方法を模索＆リサーチ」 → ローカル定量化 + 一般 agent による web リサーチ:
- 旧 LATEST.md = 1728 行 / 104KB / **~42K tokens** = cold-start 全 76K tokens の 55%
- Anthropic 公式: CLAUDE.md ≤200 行推奨、 超過で「指示遵守率が落ちる」
- Snapshot + Journal 分離 / session-reader subagent / `.claude/rules/*.md` path-scope が公式パターン

採用: Pattern 1-5 全部 (1 週間プラン)。

**Pattern 1-5 全実装 (本セッション完遂)**:

| Pattern | 実装 | サイズ変化 |
|---|---|---|
| 1. Snapshot+Journal split | `docs/sessions/STATE.md` (48 行) 新規、 旧 LATEST.md → `2026-05_archive.md` rename (履歴温存)、 `JOURNAL.md` 新規 | 104KB → 2.7KB (startup 必読分) |
| 2. session-reader subagent | `.claude/agents/session-reader.md` (Haiku、 別 200K window、 25K→400 tokens 圧縮) | on-demand call |
| 3. subdir CLAUDE.md (lazy load) | `publishers/CLAUDE.md` (publish 罠) / `scripts/CLAUDE.md` (compound workflow + カタログ) / `bot/CLAUDE.md` (slack コマンド) | 各 0.5-4KB、 該当 dir 触った時のみ |
| 4. SessionStart hook | `.claude/hooks/session-start.sh` + settings.json に登録、 JOURNAL.md > 500 行で monthly archive ローテーション | runtime 自動 prune |
| 5. CLAUDE.md trim ≤200 行 | root を 346 行 / 15.4KB → **176 行 / 7.2KB** に再構成、 startup ritual を STATE.md ベースに変更 | -53% |

**結果サイズ比較**:
- 旧 cold-start: 190KB / ~76K tokens (LATEST.md 104KB が 55%)
- 新 cold-start: **17KB / ~6.8K tokens** (auto-loaded 14.3KB + STATE.md 2.7KB)
- **削減 91%**

未採用パターン:
- MCP memory server (knowledge-graph / memcp): solo project で daemon + DB 過剰、 multi-machine 化したら再検討
- @import refactor: 公式が「節約にならない」 明言、 cosmetic only
- Cozempic 4 層 pruning: mid-session 肥大対策、 startup cost には効かない

**memory 更新**:
- `project_zenn_cap_blocked` を「slow-walk queue (旧 cap 誤診断)」 に書き換え
- MEMORY.md 索引のエントリ更新
