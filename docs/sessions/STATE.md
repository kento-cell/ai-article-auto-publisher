# STATE — Current Project State

> 起動時に最初に読む 1 file。 60 行未満で維持すること。 詳細履歴は JOURNAL.md
> / archive、 ランブックは subdir CLAUDE.md、 cross-session preferences は memory。
> AUTO セクションは `py scripts/_session_status.py` で再生成 — 手動編集すると
> 次回 run で上書きされる。

**Updated**: <!-- AUTO:updated -->
2026-06-22 06:24 JST
<!-- /AUTO:updated -->

## In Flight (今このセッションで進行中の作業)

- 6-25 朝 `/routine` (タイトル劣化警告: 「嘘だった」 系連続発生):
  learn(280 samples/**636 chunks**) → generate **5 合格/2 不合格** → publish:
  - **note 3件**: ¥0 n1d5e2ef4a597 マットレス腰痛 (**sl_006 採用**)、 ¥0
    n60154d5d337f EDWIN 夏ファッション (GetNavi)、 ¥500 ned897bbeed07
    iPhone usbliter8 脆弱性 (GetNavi、 ⚠️membership)
  - **zenn 2件 scrap**: MulmoClaude AI エージェント、 iOS Go/Rust 性能比較

  ⚠️ **タイトル劣化警告**: 3 日連続で「嘘だった」「騙される」「致命的」
  系の煽り 7 件発生 (6-23 ランニング+大学生PC、 6-25 マットレス+EDWIN+
  iPhone)。 過去事故 (「99%が知らない」 = ops_incidents #21) と完全同路線、
  **deny pattern 追加候補**。 提案: `main.py::_PUBLISH_DENY_PATTERNS` に
  「嘘(だった|でした|です)」「実は嘘」「騙される」「致命的(欠陥|失敗|ミス)」
  を追加 (要 user 判断、 即 ban すると generate yield 下がる)。

- 6-24 朝 `/routine` (catalog rotation 100% 維持 + iter10 最後の novel pocket 全当選):
  learn(280 samples/**631 chunks** ← 昨日 627+4 = 6-23 publish 反映) →
  generate **5 合格/2 不合格** (rejected: Tauri zenn、 K-beauty 化粧水 dup) →
  bulk_approve → publish:
  - **note 4件**: ¥0 n3ca3b0ff5124 観葉植物 (**gd_001/gd_002 採用**), ¥0
    n1cefedacfe26 オフィスチェア BIFMA+Aeron/Leap/コンテッサ/バロン
    (**wfh_001 採用 ← iter10 last-pocket**), ¥500 ncc692fa39a0d スマート
    ホーム Matter 1.2+SwitchBot/Aqara/Apple (**sh_001 採用 ← iter10 last-
    pocket** ⚠️membership), ¥500 n6132150d8efd 猫種 TICA/CFA/JKC+アニコム
    白書 (**pet_005 採用 ← iter10 last-pocket** ⚠️membership)
  - **zenn 1件 scrap**: Copilot App (AI/tech RSS)
  **knowledge_topics 由来 4/4 = 100% 採用維持** (昨日 100%→今日も 100%)。
  特に iter10 で agent が exhaustion 宣言した最後の追加分 (wfh/sh/pet_cat)
  が全件当選 = 『最後の novel pocket』 評価が正しかった実証。

- 6-23 朝 `/routine` (catalog rotation 効果 100% 達成):
  learn(280 samples/**627 chunks** = 昨日 621+6) → generate **4 合格/3 不合格**
  (rejected: AutoDex arXiv、 K-beauty 化粧水 dup、 レグザ Mini LED) →
  bulk_approve → publish:
  - **note 3件**: ¥0 n8ec55d87dd02 ランニングシューズ (**rn_001 採用**),
    ¥0 n3c284a80071d 大学生PC (**std_001 採用**), ¥500 n3d431c4cd205 家庭用
    エスプレッソ Breville (**cb_005 採用** ⚠️ membership 手動追加)
  - **zenn 1件 scrap**: Lift4D 4次元再構築 (arXiv 由来)
  **knowledge_topics 由来 3/3 = 100% 採用** (昨日 33%→今日 100%、 catalog
  rotation が完全稼働実証)。 タイトル「嘘だった」「騙される」 等の border-
  line 煽り (現在の deny pattern には未収録) を観測対象に。

- 6-22 朝 `/routine` (新 topics 効果検証):
  learn(280 samples/621 chunks) → generate **6 合格/1 不合格** (Cellbn エクソソーム
  rejected) → bulk_approve → publish:
  - **note 4件**: ¥0 nefaac1f92068 歯ブラシ Sonicare vs Oral-B (**orc_001 採用**),
    ¥0 nab66e3931782 韓国ウェルネス汗蒸幕 vs 瞑想 (**kw_001 採用**),
    ¥500 n2bda7c2f23e3 Galaxy Watch Ultra 2 バッテリー, ¥500 ne303807ab7f8 Jackery
    ポタ電 (⚠️ membership modal 失敗 → 手動追加リスト)
  - **zenn 2件 scrap fallback**: Windows I/O 高速化、 GitHub Copilot コスト管理
  タイトル deny pattern 全件 clean (「N人に聞いた」「99%系」 無し)。
  bias 是正後の新 topics (orc_001 oral_care, kw_001 k_wellness) が早速採用
  された = 152 topic catalog の rotation 効果実証。

  **画像再生成 (08:56 完了)**: routine 中 ChatGPT CDP 失敗 → Unsplash fallback
  4件。 user 指示で Brave 起動 (port 9222 reachable) → _regen_today_note_
  with_chatgpt.py 引数 article_id で 4件再実行 → 12画像 (cover×4+inline×8)
  全て ChatGPT 差し替え成功 (timeout 2回 retry あり)。 sweep 結果 leak 0件。
  ⚠️ TARGETS hard-coded で初回引数なしだと 6-03 K-beauty 3 件 (PDRN/シカ/
  緊急ケア) が再生成される副作用あり (致命的でないが古い記事の画像が refresh
  されてしまった)。

  **AIで遊ぼう コンテスト続編 #2 publish (14:05)**:
  user 指示で続編記事を即生成・publish。 タイトル「【運用日誌②】AIに『ネタ
  増やせ』と5回叩いた1日、 152個生成・$135燃焼・韓国偏重まで起こした #AIで
  遊ぼう」 (12,565字、 AIフェスティバル 7回言及)。 内容: 昨日 loop 10 iter
  の全記録 + K-bias 誤適用と是正 + ccusage $135 燃焼 + agent exhaustion 宣言
  + 今朝 routine の orc_001/kw_001 採用 (rotation 効果実証 33%) + Brave CDP
  事故 + image-regen 副作用 + 自己修復 2 対策。 URL: n6300a1a2f77e (¥0)。
  ChatGPT 画像 batch 1/3/5 timeout で 2 枚 ChatGPT + 2 枚 Unsplash 混在、
  cover も生成済。 ⚠️ **タグ field が再び空** (note UI 既知制限、 user 手動
  追加リストに #AIで遊ぼう 追加候補)。

- 6-21 夜 `/loop` 再起動 (iter4-5、 bias-free 22件追加): user の bias 指摘以降
  全 prompt を中立化、 既存 105 を avoid に渡して 2 イテレーションで +22 件:
  - **iter4 (+10)**: br_001 ビジネス書独立横断、 ck_001 Vermicular vs Staub、
    pr_001 Cubo Ai vs VAVA ベビーモニター、 sl_005 Oura vs Whoop、 fj_001
    Margaret Howell、 fn_001 新NISA 高配当ETF、 pd_001 日本語ポッドキャスト、
    gd_001 北欧スマート水耕、 mn_001 ミニマリズム、 tj_001 関東マイクロツーリズム
  - **iter5 (+12)**: ck_002 ホットクック vs Instant Pot、 ck_003 山口祐加自炊本、
    pr_002 抱っこ紐3社、 sl_006 マットレス3社、 pd_002 英語ポッドキャスト5本、
    gd_002, tj_002, pet_002, mc_002, wc_002, cr_002, rn_001 (running 新カテゴリ)
  **K比率 39%→32%** (37/117)。 累計 6 イテレーション +49 件 (68→117)、
  32 カテゴリ。 ScheduleWakeup 省略でループ停止、 PushNotification 送信。

- 6-21 夕方 (bias 是正 追加): user「すべて韓国？？バイアスかからないようにして
  ほしい、 リサーチしているはずだよバズのロジック」 の指摘で、 私が既存データ
  (K-beauty avg♥1.15) と memory (K-beauty 主軸計画) を**バイアスとして適用**して
  17件全部 K-prefix にしたことを自認。 「バズロジック (体裁/構造/一次情報優先)」
  はジャンル不問なので、 中立 Workflow (wiq7qzyu4) で **非K軸 10件追加**:
  hg_009 京都喫茶老舗 (イノダ/六曜社)、 hg_010 福岡屋台、 cb_005 家庭用エスプレッソ
  (Breville Bambino Plus)、 cb_006 東京ロースター (LIGHT UP/ONIBUS)、 si_004 姿勢
  ケア (ストレッチポールEX)、 sl_004 手帳術 (ほぼ日/LEUCHTTURM1917)、 pet_001
  ペット用品 (PETKIT/PETLIBRO)、 wc_001 30-40代女性キャリア、 mc_001 メンタル
  ケア (HSP)、 cr_001 編み物/刺繍 (ハマナカ)。 完全新カテゴリ 4 追加: pet_life /
  women_career / mental_care / craft。 **K-prefix 比率 44%→39%**、 累計 +27件
  (68→95)。 私の bias check 初回が overly strict (prohibited_angles の「韓国を
  持ち込まない」条文も K-bias 判定して全 false-positive)、 promise/persona のみで
  再判定して全 10件 inject 成功。

- 6-21 夕方 `/loop` 自走 (3イテレーション完走):
  user「10 --learn 埋め込んで 記事ネタ増やして」 を dynamic-mode loop で実行。
  --learn (RAG 591→621 chunks reindex 完了)、 3 イテレーションの海外バズ
  Workflow で **knowledge_topics 68→85 (+17件)** に拡大。
  - **iter1** (+8): kb_008 男性K-beauty(Laneige Homme), kb_009 スカルプケア
    (Aromatica), kb_010 Tranexamic Acid (Anua), kc_005 Netflix「Teach You
    a Lesson」, kc_006 フォトカード二次流通 $500M, hg_007 益善洞マッコリバー,
    hg_008 日本国内スペシャルティ新店, cb_004 Time Out コーヒー世界100
  - **iter2** (+4): kf_001 K-fashion SFW新興4ブランド(MÜNN/MMAM/SATUR/
    2000Archives), kfo_001 K-foodコンビニスイーツ4種, kw_001 ウェルネス
    (チムジルバン+テンプルステイ), kw_002 韓方茶3種
  - **iter3** (+5): kfra_001 韓国香水6ブランド(Tamburins他), kbody_001
    K-bodycare 5カテゴリ, kfit_001 K-popピラティス, kmed_001 渡韓美容医療
    (江南クリニック), ktech_001 K-tech ガジェット (LG StanbyME 他)
  - **新カテゴリ 8 追加**: k_fashion / k_food / k_wellness / k_fragrance /
    k_bodycare / k_fitness / k_medicine_beauty / k_tech_gadget
  各 topic は verbatim 固有名詞+URL+価格込み (ハルシ防止素材完備)。
  rotation_weight 2.0 で次回 generate から優先サンプリング、 cooldown_days 14。
  data/knowledge_topics.json は gitignored、 docs/strategy/2026-06-21_
  knowledge_topics_after_loop.json にミラー (cross-session portability)。
- 6-19 夕方 `/routine`: learn→generate **4合格/3不合格** → publish (zenn 2 scrap +
  note 2本)。 publish 内訳:
  - nddb0f29b6a04 松島かのん等身大抱き枕 (¥0、 ChatGPT 画像失敗 → Unsplash fallback)
  - ncd3ce0e3bf46 Shark扇風機 (¥0、 ChatGPT 画像失敗 → Unsplash fallback)
  - zenn scraps/e4b421222030f6 JanusMesh 3D + scraps/4a00a00d933fc3 TimeProVe
  改修発火: rag-learn=1、 hallu-guard 5回、 dup-check no near-duplicate、 タイトル捏造系
  deny clean。 不合格 3件のうち K-beauty 韓国ファッション (KIRSH title_fulfillment)。
  ⚠️ **2 つの問題検出 + 1件即修正**:
  ① **私のリグレッション** (`f23e191` の修正が間違った関数に入っていた): `_publish_note`
  は `stored` 引数を持たない関数なのに `isinstance(stored, dict)` を呼んでいて 毎 publish
  で NameError ログノイズ → image_style label persist は冗長 (chatgpt_image_batch が
  data/image_usage.jsonl で既に保存) なので **削除して clean に** (新 commit)。
  ② **ChatGPT 画像 timeout/placeholder 連発**: cover=False inline=1/3、 Brave CDP は
  alive だが ChatGPT 側 UI selector drift (ops_incidents #15 と同症状) →
  両 note とも Unsplash fallback 41KB。 user 起床後に regen 候補
- 6-18 朝 `/routine`: Brave CDP 落下→再起動→learn→generate **4合格/3不合格**
  → **note 4本** publish (zenn 不合格1=「99%が知らない」 H1 で **昨日追加の deny pattern
  が機能した実証**、 deny `9[0-9]%が知らない` が forbidden_phrases で検知して却下)。
  publish 内訳:
  - **nbcd46008985c 延禧洞カフェ** (¥0、 **kc_004 海外バズ brief 由来** = 6-16 仕込み
    の K-culture 主軸トピックがついに採用、 タイトル「【禁断】【永久保存版】2026年
    ソウルカフェ巡り！ローカルな隠れ家で見つけた『本気の心地よさ』6選」)
  - n5edc482c8fe6 E-BIKE「APE RYDER」(¥0)
  - n34739e03cbd7 SIXPAD Medical Core (¥500)
  - neb29b095c5a6 印刷現場 (¥500)
  改修発火: `[rag-learn:note] success=1` ×2、 `[hallu-guard]` 6回 (top sim 0.85-0.88)、
  `[dup-check-summary] no near-duplicate this run`、 全タイトル捏造系 deny clean。
  ⚠️ ジャンル散漫続行 (K-culture × 1 + E-BIKE + SIXPAD + 印刷) だが品質ゲート
  通過の合格分は publish ルール通り。 membership backlog 追加: (q) SIXPAD、 (r) 印刷現場
- 6-17 朝 `/routine`: learn (602 chunks、 past_articles 468 = コンテスト記事 +追加)
  → generate **5合格/2不合格** → **note 4本 + zenn 1本 scrap** publish。
  ⚠️ **タイトル捏造事故 (即修正済)**: MacBook (nc5d53fdebaf9) 公開タイトルに
  「99%の人が知らない」 = 統計捏造系を検出 → `edit_article` で「サプライチェーン
  情報で見えてきた」 に**即修正成功**。 同時に `main.py` の `_PUBLISH_DENY_PATTERNS`
  に `99%が知らない` / `9割が知らない` 系を追加 (今後再発防止)、 deny 42→44 + 単体
  テスト 7/7 PASS。
  ⚠️ **Galaxy 連発問題 (要 user 判断)**: Galaxy S27 Ultra (n08485d9b04df、 ¥0)
  が dup-check sim 0.881 で過去 Galaxy S27 Pro と類似ヒット → 私が bulk_approve 後に
  個別却下したが publish 起動とのタイミングで反映されず publish された。 過去 Galaxy
  シリーズ 4本連続 (6/05, 6/11, 6/12, 6/17) で K-beauty 主軸の戦略違反 + ジャンル
  散漫の毒 = **削除推奨だが破壊的なので user 判断**。 削除する場合: note dashboard
  で n08485d9b04df を手動 trash。
  publish 4本詳細:
  - nc5d53fdebaf9 MacBook タッチ (¥0、 タイトル修正済)
  - n08485d9b04df Galaxy S27 Ultra (¥0、 ⚠️ 4本連続のため要判断)
  - n21bac7596937 Nothing ヘッドホン (¥500)
  - ndefcc8612746 ドライヤー dreame (¥500)
  - zenn cp コマンド scrap (scraps/d3d9798c8c12f5)
  rag-learn success=1、 hallu-guard 4回、 dup-check-summary 1件 改修全発火。
- 6-17 朝 (起床後 user 依頼): **コンテスト記事に「ベクトル可視化」セクション追記**。
  `rag_graph_3d.html` (デスクトップにある plotly 3D 散布図) を Playwright で
  3アングル スクリーンショット (全体俯瞰 / K-beauty クラスタ / 防御系の島)、
  `scripts/_screenshot_rag_3d_for_contest.py`。 本文に新 H2 **「## おまけ:
  「ベクトル」を実際に見てみる」** を「## なぜ書くか」直前に挿入 (本文 8545→10182字、
  +1637字)、 RAG/embedding/591chunks/768次元/t-SNE/7コレクション凡例/守り系の島
  メカニズムを読者向けに説明。 `scripts/_inject_vector_viz_into_contest.py` で
  `edit_article` 経由 update、 inline 3枚すべて note CDN にアップロード成功、
  eyecatch も既存 ChatGPT kbeauty_poster で再アップ。 live 本文1220字反映確認、
  H2 構造健全 (8 H2、 「ベクトル」セクション 「なぜ書くか」 直前に配置)、
  捏造deny clean。 user が「実際にベクトルとはどういうものか見せてあげて」 と
  ユニークな着想で、 コンテスト記事の最強差別化要素 (技術可視化 + 透明性) を強化
- 6-17 深夜 (cron 自走): **`#AIで遊ぼう` エントリー publish 完了**
  (n444be2daa2ef、 https://note.com/<NOTE_USER>/n/n444be2daa2ef、 ¥0/can_read=True、
  ChatGPT cover+inline 4/4、 文字数 8545、 AIフェス言及 9回)。
  ① cron `8ab171fe` 6-17 00:07 fire → Brave CDP 落下→自動 launch ポーリング→UP→
  `publish_custom_post.py` 実行。 ② ChatGPT 画像 全成功 (cover 2.5MB + inline 4枚)。
  ③ Selenium publish 成功、 タイトル 「【運用日誌】noteを半年AIに全部書かせた結果、
  191本で♥0.90・今朝もNameErrorで爆死した話 #AIで遊ぼう」 反映。
  🚨 **タグ問題 (要 user 朝の手動対応 1分)**:
  publish_article の `_input_tags` 呼び出しで Selenium タグ入力が silent skip
  (publish ログに `_input_tags` 内ログ無し、 publish_settings 画面に遷移しなかった疑い)。
  自動修正で `_add_tags_to_contest_entry.py` + `_swap_in_contest_tag.py` を投入し、
  現在登録されているタグ: **#ChatGPT, #AI活用, #Claude, #AIフェスティバル** (4個)。
  **コンテスト必須の `#AIで遊ぼう` がタグ field に未追加** (5/5 上限の hashtag UI で
  「追加」ボタンが hashtag section 内に存在せず、 fill+Enter/click 全試行 fail)。
  ⚠️ **朝の最初の手動対応**: note edit 画面 → 公開に進む → ハッシュタグ欄に
  「AIで遊ぼう」 type → Enter → 更新する (5枠残 1個空きで slot あり)。
  これでコンテスト応募タグが完成。 ④ 本文には「#AIで遊ぼう」が末尾と複数箇所に
  あるので URL シェアでハッシュタグページから到達される副次ルートはある。
  ⑤ 続編プラン: 6-28(土) 朝7時 無料 『AI事件簿詳細編』、 7-5(土) 朝7時 ¥980 paid
  『自作 AI 工場の作り方』 (メンバーシップ誘導)。
- 6-16 夜→6-17 深夜: **`#AIで遊ぼう` コンテストエントリー仕込み**
  (note × AIフェスティバル 2026、 6/15-7/15、 グランプリ7万円+AIフェス賞3万円)。
  ① **戦略 Workflow 8並列** (`wupf04wzz` 海外バズ + `w9esnec6q` note公式コンテスト
  優勝作傾向 + 競合予測 + サードウェーブ文脈 + バズ機構)。 ② **空白地帯特定**:
  他応募者は『AIで創作物を作った』型で被る (Suno/Midjourney/ペット擬人化/タロット)。
  我々は『AIにnote運営を全部させた半年運用日誌』= 唯一無二の切り口。 深津CXO公式
  優先順位『一次情報・体験記録 > AI構造化 > ユニークAI生成 > 量産AI生成』に対し、
  commit log + image_usage.jsonl が一次情報そのもの。 ③ **本文 8545字** 書き上げ:
  `data/custom_posts/2026-06-21_ai_de_asobou_body.md`。 タイトル
  「【運用日誌】noteを半年AIに全部書かせた結果、 191本で♥0.90・今朝もNameErrorで
  爆死した話 #AIで遊ぼう」。 AIフェスティバル言及 **9回** (賞条件5+クリア)、
  191本/avg♥0.90/RAG 591chunks/閾値0.825/Brave CDP 9222/commit cb45a73→f23e191 全て
  verbatim。 捏造系 deny 0件 clean。 ④ **spec 仕様化**:
  `data/custom_posts/2026-06-21_ai_de_asobou.json` (price=0 無料公開必須、 tags に
  AIで遊ぼう/AIフェスティバル 含む)。 ⑤ **CronCreate 仕込み**: `8ab171fe` 6-17 00:07
  JST one-shot で `publish_custom_post.py` 起動。 publish + live API 検証 + STATE 記録
  + memory + commit + push まで自走完遂指示済 (Brave CDP 9222 落下時の自動 launch
  含む)。 ⚠️ CronCreate は session-only、 私のセッションが 22:08→00:07 維持できない場合
  publish されない → 朝 user が `py scripts/publish_custom_post.py data/custom_posts/2026-06-21_ai_de_asobou.json`
  で手動実行可能。 ⑥ **続編プラン**: 6-28(土) 無料『AI事件簿詳細編』、
  7-5(土) ¥980 paid『自作 AI 工場の作り方』(メンバーシップ誘導)。
- 6-16 (2nd): **海外バズリサーチ → kb_007/kc_004 inject → ChatGPT画像で publish**
  (user「learn してもらってバズを引いてください」)。 ① **海外バズリサーチ Workflow**
  (5並列 web search、 55 findings、 brief は `docs/strategy/2026-06-16_overseas_buzz_brief.raw.json`)。
  ② **knowledge_topics に2件 inject** (weight 99): kb_007 (PDRN+NAD+ 次世代成分、
  Vogue/Marie Claire/Refinery29/Olive Young の verbatim 素材)、 kc_004 (延禧洞4軒+
  聖水洞行列ベーカリー、 Esquire Korea/Visit Seoul)。 ③ **画像 learner ラベル
  保存パッチ** (`cb45a73` + 修正 `f23e191`): `chatgpt_image_batch` 末尾で
  `data/image_usage.jsonl` に style_label/cover_ok/inline_ok 追記、 `get_last_batch_meta`
  で article json にも保存。 ⚠️ **私のリグレッション**: 初版で `article` 変数を参照
  (`_publish_note` のスコープには無い、 正しくは `stored`) → publish 時に NameError
  → ChatGPT 画像は出来ていたのに except で Unsplash fallback (41KB) → `f23e191` で
  `stored` + 独立 try で隔離。 ④ **generate 4合格/3不合格**: kb_007 ✅ (公開タイトル
  「【禁断】2026年コスメ業界を支配する『主役』次世代成分10選。PDRN後の全知識まとめ」)、
  zenn 2本 ✅、 男性更年期障害は **オフブランドで ❌却下** (note主軸=K-beauty/K-cafe)。
  kc_004 は今回 generate に未選択 (翌日再挑戦)。 ⑤ **publish**: note 1本 (kb_007
  n1af6d977916f **¥500/paywall保持**)、 zenn 2本 scrap (scraps/d8d76f6c7cdb7c
  + scraps/4a12cd7818392f)。 ⑥ **ChatGPT 画像差し替え**: `_regen_today_note_with_chatgpt`
  に正しい slug `note-Vogue___Marie_Claire-54126286` で実行 → **cover+inline 4枚すべて
  ChatGPT kbeauty_poster preset で生成・差し替え成功** (eyecatch 286025622→286030325 .png)、
  image_usage.jsonl に `style=preset:kbeauty_poster cover_ok=True inline_ok=4/4` 記録。
  ⑦ live API price=500/can_read=False 検証、 全3本 捏造deny=clean、 Brave CDP 9222 動作中。
  **海外brief は明日以降の generate でも参照可能** (kc_004 残、 kb_007 cooldown 30 日)
- 6-16: **catchup を rich 化 (`06ba988`) + `/routine` (二重実行ガードで publish-only)**。
  ① **catchup ダイジェスト濃く**: user「内容が薄い」→ summarizer を 3-5行/250字 →
  **6-9行/400-550字** に深化 (具体数字・モデル名・技術ポイント・差別化・含意を要求)。
  **お断り文ガード**: 画像のみソースで gemma4 が「テキストをご提供ください」を出力する
  事故を `_looks_textless`(title fallback)+`_REFUSAL_RE`(検出破棄)+プロンプト禁止で根絶。
  digest cap 8/6/4→10/7/5、 **runner で長文を Slack 複数メッセージに分割送信**
  (`_chunk` <=3500字)。 ⚠️ `run_catchup.py` は `--dry` フラグ使用 (env CATCHUP_DRY_RUN
  無視で実投稿する罠、 初回薄い版が誤送信→dedup リセットして rich 再送)。 live 検証:
  **22件/3メッセージ、 avg 440字 (旧~200)、 refusal 0件**。 ② **/routine**: 今日すでに
  ~20分前に 6-16 朝フル稼働済み (下記6th=実は6-16早朝) → ガード通り generate せず
  **未publish の アイメイク(K-beauty)を publish** (n6e1654b594d6 **¥0**、 can_read=true、
  捏造deny=NONE)。 cadence 0件/日→残4 で公開。 membership 不要(¥0)
- 6-15 (6th): **`/routine` 全改修フル適用の初回稼働**. learn (full-wipe reindex
  **591 chunks**、 per-example chunking + sentinel) → generate **7合格/0不合格**
  (全 B/A) → publish: **note 1本** 韓国カフェ (nac0669e0995d **¥0**、 live
  price=0/can_read=true、 公開タイトル捏造deny=NONE)、 **zenn 2本** scrap
  (マルチモーダルAI scraps/e96e63dd6cd622、 Transformer部品分解 scraps/620a397e529e36)。
  cadence cap 本日4本目で1枠。 **改修の発火確認**: `[dup-check-summary]`(新規)、
  `[rag-learn:note] success=0 anti=1`(0.825で選択的、 旧0.55の乱射を抑制)、 hallu-guard
  8回、 ops-banner、 stale警告なし、 全タスク gemma4。 🔧 **リグレッション検出+修正**
  (`572acb1`): `--learn` auto-reindex が cp932 で UTF-8出力(私の em-dash)をデコード失敗
  →`r.stdout=None`→reindex 偽スキップ。 UTF-8 decode + None ガードで修正、 reindex 正常化。
  ⚠️ **品質懸念**: gate が **オフブランドの Reddit life-essay 再構成3本を合格**させた
  (スポーツ観戦の自国応援心理 / ふるさと納税配送トラブル / K-drama→医療批評=タイトル負け)。
  全7本が「正直、…」定型開口(gemma4 の癖)。 3本を **❌却下** (publish前に除外、
  オンブランドのみ公開)。 アイメイク(K-beauty)は✅承認で翌日繰越。 membership 不要(¥0)
- 6-15 (5th): **全生成タスクを gemma4:e4b に統一** (`4ddf24c`、 user「すべて gemma4」)。
  Workflow 4並列監査で全モデル選択箇所を洗い出し (72 findings): default 2層
  (`llm_config._DEFAULT_MODEL` / `local_llm.DEFAULT_MODEL` 両 gemma3:12b) +
  .env が writer/scorer のみ gemma4 override。 残 3タスク (summarizer/hashtag/
  regenerator) と no-arg `LocalLLM()` バイパス3箇所 (画像 distill / paid-note
  script) が gemma3 のまま判明。 対応: **コード default 2箇所を gemma4:e4b に変更**
  (移植可能=clone でも全 gemma4) + .env に 3タスク明示追加 (gitignore、 ローカル可視化)。
  **据置**: e5-base embedding / bge-reranker (生成LLMでない)、 ab_test harness、
  gemma4-era guards (C_RESCUE/scorer閾値)。 検証: 全5タスク+no-arg LocalLLM()=gemma4
  解決、 ollama 在庫あり、 hashtag live 応答、 deny 42+7+8 PASS。 ⚠️ gemma4:e4b は
  ~4B で 12b より小、 peripheral タスクの fidelity 低下可能性 (低stakes で許容)
- 6-15 (4th): **RAG 自動チューニング全完了** (`bba85dd`、 user「すべてやって完璧に
  自動でチューニング」)。 ① **threshold 自動較正ハーネス** `calibrate_rag_thresholds.py`
  (正例/負例で Youden's J grid-search、 再現可能) → **0.825** 算出 (successes
  recall1.0/fpr0.0)、 `_build_rag_learned_block` に反映 (env `RAG_LEARN_THRESHOLD`
  上書き可)。 旧0.55 の Galaxy→0.765 リーク除去、 K-beauty/AI 発火継続を実測。
  ② **reranker A/B 計測** `measure_rag_reranker.py` → **bi 5/5 vs rerank 3/5** で
  reranker は dup 検出を悪化と判明、 `RAG_RERANKER=false` が正解と確定 (想定が計測で
  覆った)。 ③ **index version sentinel** (build が書き retriever が不一致 WARNING)。
  ④ **deny 陰性corpus +5** (gadget/kbeauty/shop/news/travel 全0 hits、 42+7+**8**)。
  ⑤ **dup-check-summary** 1行を generate 終端に (観測のみ、 publish 不変)。 全段
  import/py_compile/deny42+7+8/title PASS。 詳細 memory `project_rag_migration`
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
   (m) 6-15 携帯ハサミ/シール交換文具 (nd704d3e75847 ¥500)、
   (n) 6-16 K-beauty PDRN+NAD+ 次世代成分10選 (n1af6d977916f ¥500、 ChatGPT kbeauty_poster cover+inline 4/4 差し替え済)、
   (o) 6-17 Nothing ヘッドホン (n21bac7596937 ¥500)、
   (p) 6-17 ドライヤー dreame (ndefcc8612746 ¥500)、
   (q) 6-18 SIXPAD Medical Core (n34739e03cbd7 ¥500)、
   (r) 6-18 印刷現場 (neb29b095c5a6 ¥500)。
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
- [睡眠時の心地よさに驚き！ 「Shark TURBOBLADE ハイパワータワーファン」は扇風機の…](https://note.com/<NOTE_USER>/n/ncd3ce0e3bf46?app_launch=false)
- [松島かのんをリアルサイズで体感！等身大抱き枕カバー発売中 水着違いで3種類展開 発売記念イベント…](https://note.com/<NOTE_USER>/n/nddb0f29b6a04?app_launch=false)
- [TimeProVe: Propose, then Verify for Efficient Lo…](https://zenn.dev/kento_cell/scraps/4a00a00d933fc3)
- [JanusMesh: Fast and Zero-Shot 3D Visual Illusion…](https://zenn.dev/kento_cell/scraps/e4b421222030f6)
- [グラドルが熱望した“紙じゃなきゃできない”写真集とは？「今日も下版はできません！」第121話…](https://note.com/<NOTE_USER>/n/neb29b095c5a6?app_launch=false)
<!-- /AUTO:recent -->

## Pipeline Health (auto)

<!-- AUTO:pipeline -->
- JOURNAL.md: 154 lines (rotation at 500 via SessionStart hook)
- Zenn queue head: (skipped in quick mode — run `py scripts/_session_status.py` for full probe)
- Recent commits (last 48h):
  - ac148f0 ops(topics): /loop iter10 FINAL +5 (147→152, K 24%, 62 cats) — agent declared exhaustion
  - 48bb2ab ops(topics): /loop iter9 +7 seasonal-ROI + resegment (140→147, K 25%, 59 cats)
  - 43e7ee5 ops(topics): /loop iter8 +7 super-super-niche (133→140, K 27%, 55 cats)
  - c3932e6 ops(topics): /loop iter7 +8 super-niche persona/super-local (125→133, K 30%→28%, 48 cats)
  - a5ccf84 ops(topics): /loop iter6 final +8 virgin categories (117→125, K 32%→30%, 40 categories)
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
