# STATE — Current Project State

> 起動時に最初に読む 1 file。 60 行未満で維持すること。 詳細履歴は JOURNAL.md
> / archive、 ランブックは subdir CLAUDE.md、 cross-session preferences は memory。
> AUTO セクションは `py scripts/_session_status.py` で再生成 — 手動編集すると
> 次回 run で上書きされる。

**Updated**: <!-- AUTO:updated -->
2026-07-14 09:07 JST
<!-- /AUTO:updated -->

## In Flight (今このセッションで進行中の作業)

- **7-14 朝 routine (防御ゲート初の実戦発火 + レビューで新事故 #24/#25 検出)**:
  - learn: 685 chunks / generate: 6合格/1不合格 / 承認 6件
  - publish 1回目が外部停止 (killed) → orphan 検証 (note未投稿・プロセス残ゼロ
    を実証、事故#1の再発なし) → ユーザー承認後に再開、完走
  - **7-13 恒久対策が実戦で発火**: deny ゲートが壊れた持ち越し4本
    (knowledge_topic:// 流出、修正前生成の在庫) を publish 前に阻止 (❌却下)、
    完結性ゲートが1本 (マーナ、空免責見出し) を阻止 (承認のまま保持+Slack通知)
  - publish 成功: note 4件 (PS5 ¥0 nafa05ea134c4 / 小型バッグ ¥0 n32e900f92780 /
    プロジェクター ¥500 n08979e185717 / ハンディファン ¥500 n648136dc2bba、
    live API 検証済) + zenn scrap 2件 (10de0daec2c410, f3b47480f13df7)
  - **投稿後レビュー (手順7 初回自動実施): CRITICAL 13 / WARN 8 / NOTE 4**
    - **事故 #24**: 本文H1が公開タイトルに昇格、 **¥500有料が「【完全無料】」
      タイトルで公開** (#21残存ギャップの実害化、note全4本で乖離)
    - **事故 #25**: url_cleaner の URL剥離で「出典: ROOMIE — 」ダングリング
      多発 (1記事9箇所実証、#22亜種)
    - 画像被写体不一致 note3本 (backlog#1悪化)、zenn体裁再発 (backlog#3/#4)
    - Slack 通知済、ops_incidents #24/#25 追記 + RAG 693 chunks 再ingest、
      backlog #8-11 追記
  - **user 判断=タイトル修正のみ (¥500維持) → 同日実施済**:
    - live 2本タイトル差し替え (「【完全無料】」「科学が証明した」除去) +
      ダングリング出典 計15箇所修復 (`_fix_titles_20260714.py`、live検証済)
    - **恒久対策も同日実装**: #24 3層 (H1採用全ソース化 / タイトル-価格
      矛盾ゲート+Slack / 「科学(的に)証明」deny 3箇所同期)、
      #25 根本 (_BARE_URL_RE が全角文字を食い後続文まで削除→非ASCII除外
      + dangling自動修復パス)、P3 画像クエリ汚染 (コードフェンス/出典行
      除去+媒体名blacklist)、zenn体裁 (## ## 修復+取得日正規化)
    - regression: 49 deny + 15 sanitizer + 9 completeness + 8 RAG 全PASS、
      ops #24/#25 → ✅修正済、RAG 693 chunks 再ingest
- **7-13 投稿後レビュー (RSI、 article-reviewer subagent 初運用)**:
  - `.claude/agents/article-reviewer.md` 新設 (投稿済記事を外部読者視点で
    A〜G 7カテゴリ/31項目レビューする独立エージェント、 リサーチベース設計)
  - 6記事レビュー結果: note 4本中 3本 🔴 / zenn 2本 🟡
    - **事故 #22**: knowledge_topic 記事 3本で内部 URI
      (`knowledge_topic://kc_006` 等) + 「媒体名」プレースホルダが出典として
      本文流出、 scorer が citation 誤カウントで quality-gate 素通り
    - **事故 #23**: 同 3本が mid-sentence 切断のまま publish
      (**有料 ¥500×2本が未完状態で課金公開、 約50分継続**)
  - 緊急対応 (全完了、 live API 検証済):
    - K-POPトレカ (n65306d782b03): 本文補完+ID除去、 ¥0 のまま
    - マッコリ (n660937d81cdd): **¥500→¥0 降格**+本文補完+プレースホルダ除去
    - カメラ比較 (n1ad6c673fc7b): **¥500→¥0 降格**+本文補完+ID除去+まとめ追加
  - `NotePublisher._set_free()` + `edit_article(make_free=True)` 新設
    (有料→無料の緊急降格、 一発動作確認済)
  - ops_incidents #22/#23 追記 + RAG 再ingest (685 chunks)
  - 恒久対策 全6項目 ✅完了 (commit `d41484e`、 詳細は Next Actions #0)
  - **RSIメタレビュー実施 (Codex 13件 + process audit 8件)** → 妥当な指摘を
    追加実装 (commit 後述): sanitizer regex 強化 / scorer 空出典除外 /
    fail-closed gate / Slack alert / _set_free fail-closed / routine への
    投稿後レビュー自動配線 / review_backlog.md 新設 / STATE.md 815→300行圧縮
- **7-13 朝 routine (learn→generate→承認→publish 完走)**:
  - learn: 280件学習、 RAG 676 chunks re-index (anti_patterns 8 / successes 8 /
    hallucinations 18 / ops_incidents 16 / generation_guides 70 / past_articles
    541 / thumbnail_styles 15)
  - generate: 7件生成、 スコアリング 合格7/不合格0 (zenn2 + note5、 全て総合B/
    証拠LvA)。 dup-check 1件 warning (「ループエンジニアリング…」 sim 0.888、
    後続確認で別記事と判定し publish 続行)
  - bulk_approve: 7/7 承認 (グレードC/SNS ハルシガード 引っかかり無し)
  - publish (`--free-first 2`, `NOTE_DAILY_LIMIT=4`):
    - note 4件 投稿 (**cadence cap 上限到達で今回新規5件は明日以降に持ち越し**、
      先に古い承認待ち4件が優先消化された想定通りの動作):
      1. n65306d782b03 K-POPトレカ市場 ¥0/can_read=True
      2. n62fa415c97a8 割れないグラス ¥0/can_read=True
      3. n660937d81cdd 真のマッコリ ¥500/can_read=False
      4. n1ad6c673fc7b 本気のカメラ比較 ¥500/can_read=False
      (live API 4件とも price/can_read 想定通り確認済)
    - zenn 2件 投稿: queue 満杯 (404) → scrap fallback 両方成功
      (a97d79a71be870 CAD設計, 71addcdd3a0ecd ループエンジニアリング、
      両方 HTTP 200 生存確認済)
    - **note membership 自動追加 4件とも失敗** (`membership modal open failed:
      Locator.scroll_into_view_if_needed Timeout`) → 下記 Next Actions #1 に追記
    - タイトル 6件、 捏造系 deny パターン (N人に聞いた等) 該当無し確認済
  - 明日以降持ち越し (cadence cap): 京都西陣・伏見旅、 Seoul Fashion Week、
    ケルヒャー高圧洗浄機、 眉毛アイブロウ、 マーナメッシュエコバッグ (note 5件)、
    プライムデーPS5 (前日持ち越し分、 note 1件)
- 7-2 (在宅化 + claude-in-chrome 突破 + Gemini 画像 PoC):
  1. **スケジューラ全停止**: 在宅勤務開始で ai-publish-slot-{MON..FRI} 5個 Disable。
     memory `feedback_no_scheduler` 更新済。
  2. **タイトル『嘘だった』根本修正** commit `9b0de41`: prompt 側で必殺
     テンプレ #1 の『そのまま使え』 → 『型は真似てよいが表現は毎回変える』、
     煽り節に『嘘だった』 封印明記、 数字予告系ブラケットから【100人に聞いた】
     【99%が知らない】 除去 (publish deny 済との整合)。
  3. **catchup 配信** (6-22 → 7-2 の 10日分): 22 items / 4 Slack msgs /
     avg 433字 / refusal 0。
  4. **claude-in-chrome (Chrome 拡張) が Playwright/CDP の壁を突破**:
     - Playwright/CDP は `isTrusted=false` イベントで note の React state に
       登録されず失敗し続けていた。 claude-in-chrome は実ブラウザ拡張で
       trusted human gesture (isTrusted=true) を発生。
     - **コンテスト応募 2件完了**: n444be2daa2ef (contest #1) と
       n6300a1a2f77e (contest #2) 両方で #AIで遊ぼう 参加 → 「記事が公開
       されました」 モーダル + バナー青枠 persist 確認。 fresh tab で重い
       記事 (12,565字) の renderer 凍結を回避する pattern 確立。
     - **重要発見**: コンテスト参加は「ハッシュタグ」 ではなく公開設定
       画面「お題/コンテストに参加」 セクションのバナー click → 「内容に
       同意して応募」 → 「更新する」 という別機構だった。 6-17 以来「タグ
       追加」 として全滅していたのは根本的に間違った UI を叩いていた。
     - **membership 累積 10件全消化**: Jackery / Breville / Matter / 猫種 /
       iPhone / バナナ / リュック / 洗面所 / いびき / Galaxy Watch を全て
       「すべてのプラン (全員に公開)」 プランに「追加済」。 UI 変わっていて
       「選択モード」 ではなく per-article モーダルの簡易 flow に。
     - memory `project_ai_de_asobou_contest` 更新済。
  5. **画像生成先を ChatGPT → Gemini に切替する PoC 成功**:
     - user が 7/15 で ChatGPT サブスク解約 → 現状の画像 pipeline が実質
       broken。 Gemini 3.5 Flash (無料) で代替検討。
     - 案 C (完全 Claude in Chrome) は blob URL の <a download> が拡張
       sandbox で発火せず、 base64 経由だと 1画像 90K token = $1-2 で
       月 $1200 級コストになり不成立と確定。
     - **案 B (画像だけ Gemini + Playwright、 note publish は Playwright
       継続)** に pivot。 `scripts/_gemini_poc.py` で Playwright + Brave
       CDP で Gemini 3.5 Flash に「画像を生成してください: <en prompt>」
       送信 → blob img → **canvas.toDataURL で CORS 回避 → base64 →
       PNG 1024×572 保存**、 25秒/枚 で成功実証 (token 0)。
     - **✅ 実装完了** (同セッション continuation):
       * `generators/gemini_image_generator.py` (~330行) 新規作成 —
         ChatGPTImageGenerator.generate_batch 互換 interface。
       * `chatgpt_batch_helper.py` に `is_gemini_image_gen_enabled()` 追加、
         backend 選択の 1 箇所分岐 (残りの prompt 組立/dup チェック/
         Pollinations fallback/image_usage.jsonl は全て流用維持)。
       * `.env` に `USE_GEMINI_IMAGES=1` 追加。
       * dry-run `scripts/_gemini_batch_dryrun.py` で cover+inline×2 の
         **3/3 全成功** (平均 43秒/枚、 各 1.4MB PNG、 backend=gemini、
         合計 118 秒 で ChatGPT 3×60秒=180秒 より高速)。
     - **重要な修正** (2枚目 timeout → fresh tab 化): 同一 page で `/app`
       再 navigate だと Gemini SPA state が残って image-gen ルーティング
       が再入せず 2枚目以降 timeout していた。 `_navigate_fresh_chat` で
       毎回 `new_page()` して完全にリセット、 これで 3/3 成功。
     - ChatGPT 経路は残す (`USE_GEMINI_IMAGES=0` で rollback 可能)。
     - user に生成3枚を SendUserFile で共有、 品質判断待ち。
       OK なら次の `/routine` から実本番運用。

  6. **7-3 全体監査 → Gemini backend v2 (5 欠陥修正、 全実地検証済)**:
     - **P0-1 改行→Enter 途中送信**: prompt を `"\n".join` して keyboard.
       type していた — `\n` は Enter キー入力になり style_block (複数行)
       で確実に途中送信。 `_flatten()` で全空白を単一スペース化して修正。
       (v1 dry-run が通ったのは style_block=None の偶然)
     - **P0-2 cover がバナー化されない**: ChatGPT 版 `_build_prompt(is_
       cover)` 相当が無く raw prompt 素通し → 「文字入り煽りサムネ」 の
       識別性を喪失していた。 `_compose_prompt()` で 3 分岐 (styled cover
       / click-bait banner / inline) を移植。
     - **P0-3 size 無視**: `_SIZE_PHRASE` (16:9 横長等) を全 prompt に
       付与。 実測 1024×572 で 16:9 確認。
     - **P1-4 blob 取り違え**: `_extract_png(blob_url)` で waiter が
       見つけた URL と同一の img だけを canvas 抽出。
     - **P1-5 履歴リーク (memory: 画像生成会話は必ず削除)**:
       **一時チャット (Temporary Chat) モードで構造的に解決** —
       `button[aria-label='一時チャット']` を fresh tab ごとにクリック、
       会話が保存されないので削除自動化そのものが不要。 一時チャット内で
       画像生成が動くことを実地検証済。 button が見つからない場合の
       fallback として `_cleanup_current_chat` (サイドバー展開 `side-nav-
       sparkle-button` → `gem-nav-list-item[data-test-id='conversation']`
       hover → ⋮ → 削除 → confirm、 DOM 実地調査済) を実装、 **残骸
       6 チャットの実削除で 6/6 動作検証済**。 `GEMINI_CLEANUP_CHATS`
       env (default ON)。
     - おまけ修正: v1 の `close()` が CDP attach した user の browser
       context を閉じていた (実 Brave の全ウィンドウが閉じるリスク) —
       page だけ閉じるよう修正。
     - 監査後 dry-run: temp-chat 経由 cover+inline 2/2 成功 (27-41秒/枚)。
       AUTO_LAUNCH_BRAVE_CDP=1 も初実地発火で機能確認 (port cold →
       bat 起動 → 1 秒で CDP up)。

- 7-7 夜 `/routine` 2回目 (Mac 改良取込み + 7記事全合格 + zenn article 完全復活):
  Mac から PR #2 (catchup 新ソース 6種: Bluesky×3/HF Papers/Techmeme/
  TechCrunch/Publickey/GitHub Repos) + #3 (並列 fetch/URL dedup/sort
  crash 修正) を pull。 fetch smoke: **957 items / 13.3秒 / 16 sources**
  (旧 31 items) — user の Mac 開発フローが初成立。
  learn(663 chunks) → generate **7 合格/0 不合格 (初の全合格)** → publish:
  - **zenn 2 本とも article 投稿成功** (Git failed なし = 7-4 修復完全有効):
    Observability 設計、 Fable5→Opus/Sonnet 引き継ぎ
  - **note 1件**: ¥0 n72dbbaa066a0 手帳 ほぼ日 vs LEUCHTTURM (**sl_004
    採用**、 Gemini cover+inline 4/4)
  - **持ち越し 4 本** (cap 到達、 明日自動): kc_006 フォトカード $500M、
    割れないグラス、 Anker 防犯カメラ、 スクワットイス
  Gemini backend 3 日連続成功 (通算 35/35 fallback ゼロ)。

- 7-7 朝 `/routine` + catchup (Gemini 2回目 15/15、 zenn git 修復効果確認):
  catchup (22 items/3 msgs/avg 451字/refusal 0、 gemma4 競合回避のため
  generate は catchup 完了後に順序制御) → learn(280/660 chunks) →
  generate **4 合格/3 不合合** → publish:
  - **note 3件**: ¥0 n43e5668ec7f9 30代女性転職 5サービス (**wc_002 採用**)、
    ¥0 nc4466bd46253 中洲屋台 (**hg_010 採用**)、 ¥500 n4ee23a25f80e
    山崎実業 玄関ドア (GetNavi ⚠️membership 手動)
  - **zenn**: Codex MV 量産 — **git push 成功 (97ecc19、 7-4 修復が有効)**。
    URL 404 は既知 slow-walk queue の表示遅延で、 article queue 入り +
    保険 scrap の dual-track は正常動作。
  - **Gemini backend 2回目本番も 15/15 全成功** (3記事 × cover+inline4、
    fallback ゼロ)。 2 日連続 30/30 = 実運用安定を確認。
  - knowledge_topics 由来 2/3 (wc_002 女性キャリア初当選、 hg_010 福岡屋台
    初当選 — ともに 6-21 loop 追加分)。

- 7-4 深夜 `/routine` (**Gemini backend 初本番 15/15 全成功** + zenn push 修復):
  learn(280 samples/**655 chunks**) → generate **4 合格/3 不合格** →
  bulk_approve → publish:
  - **note 3件**: ¥0 nadefc13e0f15 無印イ草スリッパ、 ¥0 n384ddb9fdc27
    Xiaomi ミニファン、 ¥500 n12677b342526 冷やしピーマン (全 GetNavi/RSS
    由来、 knowledge_topics 当選なしの日)
  - **zenn 1件**: Claude Sonnet 5 React (scrap + 後述の push 修復で
    article too — 20260703-reactclaude-sonnet-5llm が queue 入り)
  - **🎉 Gemini backend 初本番**: image_usage.jsonl で確定 —
    3 記事 × (cover 1 + inline 4) = **15/15 全成功、 backend=gemini、
    Unsplash/Pollinations fallback ゼロ**。 一時チャット + 監査 v2 修正込み。
    ※ Gemini/batch のログが publish ログに出ない (画像ファイル+jsonl で
    検証は可能)。 ログ配管は cosmetic 課題。
  - **⚠️ zenn push 滞留の真因発見&修復**: zenn-content repo の remote が
    force-update (8a89dfc→87c8f70) されて以降、 **14 commit が non-fast-
    forward で push 失敗し続けていた** (最近の zenn 全 scrap fallback の
    真犯人)。 `git stash -u → pull --rebase (14 commits) → push` で修復、
    `6cbfd04` push 済。 publishers/CLAUDE.md の「False は cap でなく
    ローカル git 問題」 が的中。 次回 routine から zenn article publish が
    復活する見込み。
  - membership 手動追加: n12677b342526 (ピーマン ¥500) 1件。

- (6月分の In Flight ログは docs/sessions/2026-06_archive.md へ移設 — 7-13 肥大解消)

## Next Actions (優先度順、 各セッションで bump、 手動メンテ)

0. ~~🔴 事故 #22/#23 の恒久対策~~ **✅完了 (7-13 同日、 全6項目)**:
   (a) prompt 上書き + sanitizer 内部URIスクラブ3形態、 (b) scorer 内部URI除外
   + knowledge_topics citation exempt、 (c) deny 3箇所同期
   (settings/example/_PUBLISH_DENY)、 (d) 完結性 2層ゲート (生成側 trim +
   publish 側 hard block)、 (e) アフィリ family 明示ルーティング
   (`_FAMILY_GENRE_MAP`、 未知 family は default 固定)、 (f) knowledge_topics
   の stored title を本文 H1 で置換 (slug/Sheets/画像クエリもクリーン化)。
   regression: 45 deny + 11 sanitizer + 7 completeness + 8 RAG 全PASS。
   詳細: ops_incidents #22/#23 (✅修正済に更新済)
1. **note membership 手動追加 — 有料記事** (auto-add 失敗、 手動確実):
   (a) 6-02 PDRN (n17f9115b4383)、 (b) 6-03 韓国コスメ アンチエイジング (n44ae338eca1e)、
   (c) 6-04 ダウンタイム/HIFU (n065ae332ccd4)、
   (d) 6-08 韓国美容医療トレンド5 (n5c27f9e2d39a ¥500)、
   (e) 6-08 Copilot活用 (nc24c482dcd94 ¥500)、 (f) 6-08 エクセル/ワード数式 (nd085284d5bdf ¥500)、
   (g) 6-09 目の日焼け/眼鏡市場 (nbcf9df14e410 ¥500)、
   (h) 6-10 ティファール電気ケトル (n552e052f7be2 ¥500)、
   (i) 6-11 カロッツェリア Dolby Atmos (nd70c0d90f5f0 ¥500)、
   (j) 6-11 シャオミ激安スピーカー (n54cdce174d62 ¥500)、
   (k) 6-12 Galaxy Z Fold8 ディスプレイ (nef4720dcb32f ¥500)、
   (l) 6-12 推し活戦略=和泉芳怜記事 (n12e336a94735 ¥500)、
   (m) 6-15 携帯ハサミ/シール交換文具 (nd704d3e75847 ¥500)、
   (n) 6-16 K-beauty PDRN+NAD+ 次世代成分10選 (n1af6d977916f ¥500、 ChatGPT kbeauty_poster cover+inline 4/4 差し替え済)、
   (o) 6-17 Nothing ヘッドホン (n21bac7596937 ¥500)、
   (p) 6-17 ドライヤー dreame (ndefcc8612746 ¥500)、
   (q) 6-18 SIXPAD Medical Core (n34739e03cbd7 ¥500)、
   (r) 6-18 印刷現場 (neb29b095c5a6 ¥500)、
   ~~(s) 7-13 真のマッコリ巡り~~ ~~(t) 7-13 本気のカメラ比較~~
   → **不要化 (7-13 レビュー後 ¥0 降格、 事故 #23)**。
   `/notes`→記事 ⋮→「メンバーシップ特典追加・解除」→チェック→「メンバー全員に
   公開」の「追加」。 (無料記事は membership 不要)。 累計 backlog も同様。
   ⚠️ (m) は公開タイトル末尾に「（35文字）」混入 (コードは `2bd045c` で修正済、
   既公開分のみ残存) → membership 追加ついでにタイトルから「（35文字）」を手動削除推奨
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
- [2026年6月時点で在庫がある (新品 OR 中古並品) 3機種 (FUJIFILM X100V…](https://note.com/<NOTE_USER>/n/n1ad6c673fc7b?app_launch=false)
- [(a) Jongno (鍾路) 区に120軒のtraditional makgeolli est…](https://note.com/<NOTE_USER>/n/n660937d81cdd?app_launch=false)
- [(a) 2026年に$500M規模・rare cardが$200〜$1000+で取引される市場の…](https://note.com/<NOTE_USER>/n/n65306d782b03?app_launch=false)
- [ループエンジニアリングをGitHub Copilotで組めるか調べてみた…](https://zenn.dev/kento_cell/scraps/71addcdd3a0ecd)
- [AIと一緒にCAD設計できるソフト「cad-coworker」…](https://zenn.dev/kento_cell/scraps/a97d79a71be870)
<!-- /AUTO:recent -->

## Pipeline Health (auto)

<!-- AUTO:pipeline -->
- JOURNAL.md: 154 lines (rotation at 500 via SessionStart hook)
- Zenn queue head: (skipped in quick mode — run `py scripts/_session_status.py` for full probe)
- Recent commits (last 48h):
  - a50bf96 sec(pii): pre-commit に PII スキャン常設 + 残存 path 露出 2 件マスク
  - 6905eb7 fix(pii): note ハンドル露出の根本対策 — _session_status.py がマスクの上書き元だった
  - d017226 feat(catchup): 同一ニュースのトピックレベル重複折りたたみ
  - fdee11e docs: review_backlog #2/#6 を対応済みに更新 (a2b047d)
  - a2b047d fix(sanitizer): 空の免責見出し除去 + RAG鮮度警告 + knowledge 3週間分の追跡漏れ解消
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
