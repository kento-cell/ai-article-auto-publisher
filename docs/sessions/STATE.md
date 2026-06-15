# STATE — Current Project State

> 起動時に最初に読む 1 file。 60 行未満で維持すること。 詳細履歴は JOURNAL.md
> / archive、 ランブックは subdir CLAUDE.md、 cross-session preferences は memory。
> AUTO セクションは `py scripts/_session_status.py` で再生成 — 手動編集すると
> 次回 run で上書きされる。

**Updated**: <!-- AUTO:updated -->
2026-06-15 07:18 JST
<!-- /AUTO:updated -->

## In Flight (今このセッションで進行中の作業)

- 6-15 (2nd): **RAG 有効性レビュー + 自走改良 (壊さず)**。 実コード+今朝の generate
  ログで監査 → 「配線済みだが死蔵」3件特定 (reranker dead-code、 rag-learn が
  static fallback、 dup-check log-only)。 安全な改良を deny regression
  (42+7+3、 clean-tech=0 不変) で都度検証しつつ実施: ① **hallu-guard multi-query
  を `RAG_RERANKER` から独立** (`d2c69c7`、 RAG_RERANKER=false で single-query
  退行していたバグ修正、 ログラベル rerank→sim)。 ② **学習2コレクションの per-example
  chunking** (`a92c843`、 `_load_learning_chunks`、 具体例を個別 chunk 化)。 再構築後
  anti 2→7・succ 3→8・hallu 18不変、 計 567→582。 実検索で rag-learn 発火確認
  (K-beauty 0.855/AI副業 0.873、 Galaxy 0.765 で誤マッチせず)。 **未対応 (要判断)**:
  reranker ON 計測 (メモリ圧 trade-off)、 dup-check soft-gate 化 (publish 判定波及)。
  詳細 memory `project_rag_migration`
- 6-15 (3rd): **RAG 改良の end-to-end 検証 + Codex レビュー対応**。 ユーザー指摘
  「GPT5.4 も Gemma3 も使ってない」を受け、 ①**Gemma3 実生成 (`--dry-run`)** で
  `[rag-learn:note] success=3 anti=3 (block=827 chars)` 発火を確認 (embedding でなく
  実LLM経路で chunking 改良が効くことを実証、 監査時 0→3)。 ②**Codex(GPT-5.4) 独立
  レビュー** で実バグ検出: `_load_learning_chunks` が example 分割時に指示 prose を
  破棄 → **`f99e4ad` で residual chunk 化修正** (anti 7→8、 prose 0.845 で取得可、
  deny 42+7+3 不変)。 **未対応 Codex 指摘** (memory に記録): threshold 0.55 calibration
  (#1、 私の「誤マッチせず」は不正確=0.765>0.55 で当たる)、 `_INDEX_VERSION` 自動無効化
  (#3、 実害低)、 RAG陰性テスト拡充 (#4)。 dry-run は proof 取得後 TaskStop で停止
  (Sheets/投稿なしで副作用ゼロ)
- 6-15: **`/routine` 3回目稼働完遂**. learn (280 + RAG 再index **567 chunks**) →
  generate **5合格 / 2不合格** (却下: K-beauty テクスチャー=title_fulfillment
  shop 15/20、 Siri AI=`〇〇について教えて` 伏字 forbidden) → bulk_approve 5/0 →
  publish: **zenn 2本** queue git失敗→scrap (Fable5ローカルLLMエージェント
  scraps/643f20b2db9ef8、 Copilot代替OpenCode Go scraps/02be9d7754abc8)、
  **note 3本** (NOTE_DAILY_LIMIT=4 + free-first 2): 岸みゆ写真集
  (n6a931654eb90 **¥0**)、 上西怜ランジェリー (nc6651f484187 **¥0**)、
  携帯ハサミ/シール交換文具 (nd704d3e75847 **¥500**)。 live API 全3本
  price/can_read 検証済 (¥0×2 can_read=true、 ¥500 can_read=false paywall)、
  捏造系 deny (N人に聞いた等) 検知0。 ⚠️ **note 2本がグラビア寄り** (岸みゆ/上西怜、
  品質ゲートは合格・煽りブラケットは本文回収型)。 membership auto-add 全fail (既知)。
  🔧 **タイトル artifact 修正 (`2bd045c`)**: 携帯ハサミ note の公開タイトル末尾に
  プロンプトの文字数指示「（35文字）」が漏出 (本文 H1→`_extract_japanese_title`
  抽出経由、 incident #21 の残ギャップ)。 `_strip_title_meta` で
  （N文字）/(N〜M文字)/【N文字】 を抽出時除去 (正規ブラケットは保持)、 deny
  test 42+7+3 PASS。 **既公開ライブタイトルは手動修正候補** (Next Actions #1-m、
  Selenium 編集コスト高 + no-exhaustive-cleanup 方針で自走修正せず)
- 6-12: **`/routine` 2回目稼働完遂**. learn (280 + RAG 再index) → generate
  **4合格 / 3不合格** (却下: 「Fable5自分以上に信頼」=`〇〇`伏字、 韓国カフェ=title
  fulfillment+伏字、 エクソソーム=`〇〇mg/10ml`+`〇〇大学の研究` 伏字 deny) →
  bulk_approve 4/0 → publish: **zenn 1本** queue 404→scrap (Mythos 5
  scraps/42b5e7ff0a28db)、 **note 4本** (NOTE_DAILY_LIMIT=4 + free-first 2):
  Galaxy S27 Pro バッテリー (n3570c3d68048 **¥0**)、 K-POPメイク再現
  (n1bb1790e9701 **¥0**)、 Galaxy Z Fold8 ディスプレイ (nef4720dcb32f **¥500**)、
  推し活戦略=和泉芳怜記事 (n12e336a94735 **¥500**、 user 方針継続で publish)。
  live API 全4本 price/can_read 検証済、 タイトル捏造系 deny 検知0。 ChatGPT 画像
  CDP 9222 動作中継続、 membership auto-add は既知の fail
- 6-11: **`/routine` 本番初稼働完遂** (履歴書き換え後のクリーン状態で). learn
  (280件 + RAG 再index 555 chunks) → generate **7合格/0不合格** (ops-banner/
  rag-coverage 全段発火、 healthy) → bulk_approve 7/0 → publish:
  **zenn 2本** queue 404→scrap (Fable5 review scraps/2c181f8a112c1b、 Nuxt Pinia
  scraps/206452d4a128b0)、 **note 4本** (NOTE_DAILY_LIMIT=4 + free-first 2):
  iOS 27 Siriモード (n8d95295b09ae **¥0**)、 アイドル誌構造分析=森脇梨々夏記事
  (nddf849187aa9 **¥0**、 user 承認で publish)、 カロッツェリア Dolby Atmos
  (nd70c0d90f5f0 **¥500**)、 シャオミ激安スピーカー (n54cdce174d62 **¥500**)。
  Galaxy S27 Pro は cadence cap 4 到達で翌日繰越。 live API で全4本
  price/can_read 検証済、 捏造系 deny pattern 検知0。 ChatGPT 画像 CDP 9222 動作中
  (前回監査セッションから brave CDP 起動継続)、 membership auto-add は既知の fail
- 6-11: **公開7repo セキュリティ再監査 + 全件対応 (Fable5 契機)**。 3 subagent 並列
  (PII/secrets 全履歴 / 脆弱性 / dotfiles+残). **実キー漏洩ゼロ確認**。 対応:
  ① **ai-article 履歴書き換え** — author 漢字フルネーム31commit→「Kento」統一 +
  `C:\Users\kanaz`→`C:\Users\user` (blob+message)、 git filter-repo (mailmap +
  replace-text/-message)、 branch protection 一時解除→force push→即復元、 リモート
  GitHub API で 0 件検証、 ローカル stale branch 削除+gc。
  ② **SWELL** (HIGH) — CORS 反射→allowlist (localhost+*.manuspre.computer) +
  image-proxy SSRF (host検証+redirect:error) + .gitignore に .env (`b2b2a51`)。
  ③ **zenn-content** — 経歴記述 (7月生成AIチーム転職/SIer/副業) を一般化 (`a4555d2`、
  ライブ反映)。 ④ **claude-dotfiles** (HIGH) — `cat *` 削除 + codex-review `$TARGET`
  注入修正 (`816e551`)。 ⑤ **Lp** — 架空サロンの実在地番/氏名→明示ダミー (`55edb6f`)。
  ⑥ **slide-forge** — CSP script-src 分離 + 鍵パス redact (`bd7bf8d`)。 ⑦ ai-article
  ワンショットの zenn handle env-var 化 (`c922bf9`)。 ⑧ **zenn-content 履歴書き換え** (user 承認、 6-11): 旧経歴文 (SIer/7月転職/副業) を
  該当 2 行の一般化テキストへ replace-text で除去、 protection 一時解除→force push→
  復元、 リモート API で現行記事0件+全100commit author=Kento 検証済。 ⚠️ GitHub は
  unreferenced 旧 SHA を background GC まで full-SHA 直アクセスで保持しうる (5-19 同様、
  完全 purge は GitHub Support 依頼が必要)。 waterfall-review-app は PoC/デプロイなしで
  MEDIUM 据置 (未対応、 ポートフォリオ価値優先、 user 判断待ち)
- 6-10 (5th): **`/routine` テスト運用完了 — 実地で1バグ検出・修正**。 二重実行
  ガード正常 (今日 generate 済み→publish-only path)。 初回 publish で
  `NOTE_CADENCE_CAP=4` が効かず繰越→ **変数取り違え発見: CAP は on/off ブール、
  本数上限は `NOTE_DAILY_LIMIT`** (main.py:4314)。 routine.md 修正後
  `NOTE_DAILY_LIMIT=4` で再実行: **note 2本 ¥0 publish 成功** (消しゴム
  nbd9c81dd52b3、 シェーバー n9ebcbdcc3d11、 live検証 price=0/can_read=true)。
  cadence「上限4 残3」発火確認、 free-first 2 の ¥0 強制確認、 公開タイトルは
  誇張系ブラケットのみ (捏造系なし、 deny 通過)。 membership modal fail は無料
  記事なので無問題。 本日 note 計4本 (¥500×1 + ¥0×3)、 6本/日 enforcement 圏外
- 6-10 (4th): **朝のフルパイプラインを `/routine` カスタムコマンド化**
  (`.claude/commands/routine.md`)。 user が /schedule (クラウド=ローカル資源不可) と
  OS Task Scheduler (明示拒否) とセッション内 cron (7日失効で脆い、登録→削除済) を
  比較して手動コマンドに確定。 運用: 朝 CC を開いて `/routine` → learn→generate→
  全承認→publish (`NOTE_CADENCE_CAP=4` + `--free-first 2`、 無料2+有料2+zenn2-3
  目標、 品質ゲート不変)。 同日二重実行ガード指示も込み。 memory
  `feedback_no_scheduler` 更新済
- 6-10 (3rd): **Fable 5 記事の画像を ChatGPT 生成に差し替え** (user 指示
  「Brave 落として再起動して画像差し替え」)。 Brave full kill →
  `launch_brave_cdp.bat` で CDP 9222 再起動 → custom_post は store に無いため
  synthetic entry (`note-Fable5発表まとめ-custom0610.json`) を作成して
  `_regen_today_note_with_chatgpt.py` を positional slug + `--genre "AI /
  technology news"` で実行。 **cover+inline 4/4 生成・差し替え成功**、 live 検証
  (price=0/can_read=true/inline4) OK、 chat leak sweep 1 件削除。 ⚠️ 注意:
  regen の TARGETS デフォルトは 6-03 の旧 K-beauty 3 本のまま (引数なし実行は
  事故るので必ず positional slug 指定)
- 6-10 (2nd): **Fable 5 発表まとめ note を custom_post で無料 publish** (user
  指示「Fableまとめ note、無料でいい」)。 一次ソース (Anthropic 公式 6-09 発表 +
  TechCrunch/CNBC) のみで手書き、 公称は公称と明示、 数値は全て出典付き。
  ndb39bec78631、 ¥0/can_read=true/eyecatch+inline4 live検証済。 spec は
  `data/custom_posts/fable5_summary_2026-06-10.json`。 無料なので membership
  不要。 ⚠️ サブスク補足: Fable 5 は 6/22 まで Pro/Max 追加課金なし、 6/23
  以降 usage credits 必要 (公式)
- 6-10: **daily pipeline (generate→全承認→publish auto価格) 完遂 + タイトル捏造
  事故対応**。 generate **5合格 / 2不合格** (却下: K-POPメイク=title負け、
  K-beautyテクスチャー=shop数6/20)。 bulk_approve 5/0。 publish: **zenn 2本**
  queue満杯404→scrap (オントロジー scraps/f34b74dffc393e、 MySQL→PostgreSQL
  scraps/fb51639f490b4a)、 **note 1本** ティファール電気ケトル (n552e052f7be2、
  B/A→¥500、 live API 価格検証済)。 cadence cap で note 2本 (消しゴム/シェーバー)
  翌日繰越。 membership auto-add 失敗 (既知)。 **🔴事故#21**: 旧 `_TITLE_BRACKETS`
  の「100人に聞いた」が本文H1→日本語タイトル抽出経由で scrap タイトルに捏造公開
  → live 修正済 (`_fix_scrap_title_0610.py`) + bracket 事実主張型5件除去 +
  `\d+人に聞いた` deny 3箇所同期 + テスト 42 deny 化 + RAG 再ingest (555 chunks)。
  詳細 ops_incidents #21。 残ギャップ: 抽出タイトルは品質ゲート未通過 (How to apply 参照)。
  ※ ChatGPT画像 CDP未起動→Unsplash fallback (既知)。 Claude Code は npm版
  削除→ネイティブ版へ一本化 (v2.1.170)
- 6-09 (2nd): **2回目 generate→全承認→publish ALL FREE 完遂** (user 追加指示
  「フリー記事の生成も note」)。 generate **5合格 / 2不合格** (却下: こぐれひでこ
  =C title負け、 Amazonタイムセール=no grounding)。 bulk_approve 5/0。 publish
  `--free-first 999` + `NOTE_CADENCE_CAP=0`: **note 3本すべて ¥0** (秒針自動巻き時計
  ndce5692a1f19、 山崎実業/洗面脱衣室 nec4313794bf3、 リストレスト na60583526f49)、
  **zenn 2本** queue満杯→scrap (3D動画World Model scraps/9a4b1af242e6d9、 LLM記憶+
  想像 scraps/3011d8955b7aa3)。 無料記事なので membership 不要。 ChatGPT画像は
  CDP未起動継続で Unsplash fallback
- 6-09: **フル daily pipeline (generate→全承認→publish auto価格) 完遂**。 RAG
  完全復活確認 (sentence_transformers/torch import OK、 `[ops-banner:generate]`
  3件 + `rag-learn`/`hallu-guard`/`rag-coverage` 全段発火)。 generate **3合格 /
  4不合格** (却下: K-POPメイク、 韓国カフェ=title_fulfillment Instagram言及なし、
  K-beautyテクスチャー=shop数<20、 エクソソーム=forbidden_phrases「〇〇濃度」)。
  bulk_approve 3/0。 publish: **zenn 2本** queue満杯→scrap (LLM8割コード保守
  scraps/8506a21a6bc5f1、 Rust+Slint GUI scraps/d227ec736bc1ce)、 **note 1本**
  「目の日焼け/眼鏡市場サングラス計画」 (nbcf9df14e410、 B/A→¥500 paid)。 note 1本
  のみで cadence 繰越なし。 ⚠️ ChatGPT画像 CDP未起動 (AUTO_LAUNCH_BRAVE_CDP=0)
  →Unsplash fallback (cover only, inline 0)。 ⚠️ membership「追加」not found→手動要
- 6-08: **learn→generate→全承認→publish (auto価格) 完遂**。 generate 6 合格 /
  1 不合格 (白T: word_count + title負け + heading)。 bulk_approve 6/0。 publish
  1巡目: **zenn 2 本** queue満杯404→scrap (scraps/a1d2661b3aaf48、 2d86c17ef46ff5)、
  **note 1 本** 韓国美容医療トレンド5 (n5c27f9e2d39a、 B/A→¥500)。 cadence cap (1/日)
  で note 3 本繰越→ user 指示で **グラビア記事 (横野すみれ BOMB Love) を ❌却下で除外**、
  残テクニカル 2 本を `NOTE_CADENCE_CAP=0` で publish: Copilot活用 (nc24c482dcd94、
  B/A→¥500)、 エクセル/ワード数式 (nd085284d5bdf、 B/A→¥500)。 **note 計3本すべて
  ¥500 paid だが membership「追加」ボタン not found→手動 membership 追加要 (既知)**。
  ChatGPT画像 Brave CDP未起動 (AUTO_LAUNCH_BRAVE_CDP=0) で失敗→Unsplash fallback。
  ⚠️ **venv 欠落**: defusedxml 追加導入で import 復旧、 sentence_transformers/torch
  未導入で **RAG 無効 (grounding 弱)** — 次回 generate 前に要再導入
- 6-05: **learn→generate→全承認→publish ALL FREE 完遂**。 learn (280 サンプル +
  RAG 530 chunks 再index)。 generate 5 合格 / 2 不合格 (title_fulfillment +
  no-grounding で却下)。 bulk_approve 5/0。 publish: **新規 `NOTE_FORCE_FREE=1`
  env-gate** を main.py に追加 (`9598439`、 determine_price の grade 課金を ¥0 強制、
  default 挙動不変)。 cadence cap (1/日) で初回 1 本→user 指示で `NOTE_CADENCE_CAP=0`
  再 publish。 **note 計 5 本すべて ¥0** (live API で price=0/can_read=true 検証済):
  Apple×Google (n168526d27318)、 Galaxy S27 繰越 (nfa2f68cba481)、 出張コーヒー
  ポケットスケール (naf5b4a4eda56)、 89g カード型工具 (nef426e1b12e3)、 トンボ
  エアプレス (n26fe4b0fdf13)。 **zenn 2 本** queue 満杯 404→scrap
  (scraps/726b9e498708ff、 c0569b37763a87)。 membership add は失敗 (無料記事は不要)。
  ChatGPT 画像 vision-eval FAIL→Unsplash fallback (既知)
- 6-04: **generate→全承認→publish 完遂**。 生成 5 合格 / 2 不合格
  (forbidden_phrases + title_fulfillment で自動却下)。 `bulk_approve.py` で
  5 件承認 (0 skip)。 publish: **note 1 本** 「ダウンタイムが嘘だった (HIFU/
  ダーマペン)」 (n065ae332ccd4、 B/A→¥500 想定だが log に価格確認行なし=要 live 確認)、
  **zenn 2 本** queue 満杯 404→scrap (scraps/1514240e86a601、 2fab3f5ce9d181)。
  note 2 本 (Apple×Google / Galaxy S27) は cadence cap で翌日繰越。
  ⚠️ note publish 時 ChatGPT 画像生成失敗 (cover=False inline=0/4)→Unsplash cover
  fallback ([ops-banner:image] 発火)。 membership auto-add 失敗 (既知、 手動要)
- 6-04: **AI 内部 技術仕様書 (xlsx) を PII 監査 → commit** (`c0a7301`)。
  23 シート (概要 + 図 7 + 詳細 15: パイプライン/エージェント/LLM/プロンプト/
  構成/客観・主観・集約スコア/RAG/ハルシ/画像 AI/トレンド/ハッシュタグ/主要
  param/ファイル対応表)。 生成器 2 本 (`_build_ai_tech_spec_xlsx.py` +
  Pillow 図 `_ai_spec_diagrams.py`) も commit、 中間 PNG `docs/_spec_assets/`
  は gitignore (xlsx に埋込済)。 公開 repo 監査: handle/mail/実名/key/user
  path 0 件、 localhost endpoint と config フラグ名のみで clean
- 6-03: ①K-beauty 3 本 (PDRN/シカ/トラブル別) を kbeauty_poster preset で画像 regen
  → edit_article 差し替え (uploaded=3/3、 og:image 新 .png、 paywall 保持、 chat leak 0)。
  `_regen_today_note_with_chatgpt.py` を `--preset`/`--genre` + CDP-safe に一般化 (`bc8185d`)。
  ②generate→全承認→publish: 登録 3 件 (zenn 2 + note 1)。 note 4 本は客観不合格
  (title 負け/forbidden)、 5 本 dedup skip、 収集側も Reddit 403 + 美容 RSS 複数 dead。
  publish 結果: **note 1 本有料** 「韓国コスメのアンチエイジング成分は嘘だった」
  (n44ae338eca1e、 B/A→¥500、 live 価格確認済)、 **zenn 2 本** は queue 満杯 404→scrap
  (scraps/e9f3e6ee99f0d9、 d8fe360be52b38、 両 200)。 「無料(zenn)+有料(note)両方」 は
  user 承認の解釈で成立。 membership auto-add は失敗 (best-effort、 手動追加要)
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
   (m) 6-15 携帯ハサミ/シール交換文具 (nd704d3e75847 ¥500)。
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
- [和泉芳怜、ビキニ姿でたわわな柔らか美ボディ披露…](https://note.com/kento_kanazawa/n/n12e336a94735?app_launch=false)
- [きめ細かさの限界へ！ 次期Galaxy Z Fold8、ディスプレイの鮮明さがさらに向上か…](https://note.com/kento_kanazawa/n/nef4720dcb32f?app_launch=false)
- [K-POP 4 世代 主要グループ メンバー別 メイク 3-5 タイプ + 再現に必要な日本入手…](https://note.com/kento_kanazawa/n/n1bb1790e9701?app_launch=false)
- [Anthropicの新モデル「Claude Fable 5 & Mythos 5」を徹底解説…](https://zenn.dev/kento_cell/scraps/42b5e7ff0a28db)
- [スタミナに注目！ 次期「Galaxy S27 Pro」は6.5型で5000mAhバッテリー搭載か…](https://note.com/kento_kanazawa/n/n3570c3d68048?app_launch=false)
<!-- /AUTO:recent -->

## Pipeline Health (auto)

<!-- AUTO:pipeline -->
- JOURNAL.md: 154 lines (rotation at 500 via SessionStart hook)
- Zenn queue head: (skipped in quick mode — run `py scripts/_session_status.py` for full probe)
- Recent commits (last 48h):
  - (no commits in last 48h)
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
