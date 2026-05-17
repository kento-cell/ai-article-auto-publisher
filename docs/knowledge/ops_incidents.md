# 運用インシデント・レジストリ

_最終更新: 2026-05-17_

ハルシネーション(`hallucination_registry.md`)とは別に、**運用上の手戻り**を
1事案 1 H2 セクションで集約する。retry / re-publish / orphan / UI セレクタ
ドリフト / 環境変数 syntax の落とし穴など、code-only ではなくフロー全体に
影響する事象。

このファイルは RAG (chromadb `ops_incidents` collection) に embed されている。
generate / publish の前段で類似度マッチした事案を Critic / publisher に
警告として流す。**新事故時はここに 1事案追加 → `py scripts/build_rag_index.py`
で re-ingest** が運用ルール。

---

## カテゴリ別サマリ

| #  | カテゴリ                  | 観測日       | コード対策                                    | ステータス |
|----|---------------------------|--------------|-----------------------------------------------|------------|
| 1  | killed publish → orphan note URL | 2026-05-14 | `_delete_old_paid_dupes.py` + Sheets 監査     | ✅ 当該分削除済 (恒久対策未) |
| 2  | edit_article 有料記事 → 「有料エリア設定」ステップ欠落 | 2026-05-14 | publishers/note_publisher.py に paid-flow step 追加 | ✅ 修正済 |
| 3  | ChatGPT image gen → MD5 同一画像 (note logo) を 11連 | 2026-05-14 | Turnstile 許可 + 50KB minimum size guard      | ✅ 修正済 (gate 層) |
| 4  | `rotation_weight=0` が 0.01 で floor される | 2026-05-14 | collectors/knowledge_topics_collector.py: rw≤0 or disabled_reason で完全除外 | ✅ 修正済 |
| 5  | Sheets 不合格 cooldown の timestamp parse 失敗 | 2026-05-14 | main.py `_recently_rejected_titles` に strptime 多形式 fallback | ✅ 修正済 |
| 6  | Writer Gemma3 が `## H2` 構文を ~50% で守らない | 2026-05-14 | main.py `_fix_bold_pseudo_headings` post-processor | ✅ 修正済 |
| 7  | Writer が短いソース → 一般解説に Scope Drift | 2026-05-14 | prompts.yaml に「スコープから逸脱しない」+「架空引用禁止」 | ✅ 修正済 (prompt 層) |
| 8  | hallu-veto wiring が ScoreAggregator に効いていない | 2026-05-14 夜 | main.py で `subj_result["accuracy"]` を top-level に書く + blocking_issues に追加 (Codex Critical #1) | ✅ 修正済 |
| 9  | `rotation_weight: 0` が `float(... or 1.0)` で 1.0 に戻る | 2026-05-14 夜 | knowledge_topics_collector.py で `raw is None or raw == ""` チェック分離 (Codex Critical #4) | ✅ 修正済 |
| 10 | ChatGPT `_start_new_chat()` がチャットを実リセットしない | 2026-05-14 夜 | about:blank 経由 + 「新しいチャット」ボタン click + assistant-turn count 検証 (Codex High #8) | ✅ 修正済 |
| 11 | ChatGPT batch で MD5 同一画像 11連検出されず通る | 2026-05-14 夜 | chatgpt_batch_helper.py で batch 内 md5 衝突を検出し全 collisions を invalidate (Codex Critical #3 part) | ✅ 修正済 |
| 12 | sanitizer `_EMPTY_BULLET_SINGLE_RE` 誤爆 (`- メリット:` 削除) | 2026-05-14 夜 | URL/reference label (公式/サイト/ニュース/URL/出典 等) 限定に変更 (Codex Medium) | ✅ 修正済 |
| 13 | borderline-B regen feedback が旧 4000-5500 target で「具体例厚く」と促す → 偽引用増殖 | 2026-05-14 夜 | new 2200-3500 target + 「元ソース外の固有名詞は追加禁止」明記 (Codex Critical #2) | ✅ 修正済 |
| 14 | Writer prompt の「△△の専門家は〜と指摘」型が架空引用誘発 | 2026-05-14 夜 | prompts.yaml で 「肩書きベース引用は元ソース URL 裏取り必須」明示 (Codex High #5) | ✅ 修正済 |
| 15 | ChatGPT 画像セレクタ漂流 → 23618B placeholder → Unsplash 連発 | 2026-05-15 | chatgpt_image_generator.py セレクタを `[data-testid^=conversation-turn]` に修正 + 画像パイプラインを RAG `ops_incidents` に配線 | ✅ 修正済 |
| 16 | Phase 2 で forbidden regex の catastrophic backtracking → 30分ハング | 2026-05-15 | settings.yaml の接続詞 regex を 1段 quantifier の線形形に書換 + objective_scorer に接続詞 count gate | ✅ 修正済 |
| 17 | RAG retriever が記事ごとに SentenceTransformer 再生成 → HF Hub HEAD で CloseWait ハング疑い | 2026-05-15 | `.env` に `HF_HUB_OFFLINE=1` `TRANSFORMERS_OFFLINE=1` (cache 前提、外部通信ゼロ) | ✅ 緩和済 |
| 18 | note 記事が見出しだけから生成され全引用が捏造 (Reddit リンク投稿は `selftext` 空 + Codex grounding 無効) | 2026-05-17 | main.py `_fetch_article_text` / `_backfill_source_content` でリンク先本文を取得 → grounding gate に `has_source_content` 追加 | ✅ 修正済 |

---

## 1. killed publish → orphan note URL

**事象:** 2026-05-14 publish 中の Python プロセスを kill した結果、note.com 側には
記事が posted 済みだが Sheets の status は ✅承認 (or ⏳承認待ち) のまま残った。
次回 publish_approved が同行を再び publish し、note.com 上で同一記事が **複数 URL** で
公開される事故。今回は 5 Years $5M / Cisco の 2件で確認。

**原因:** publish_approved は `note_publisher.publish_article()` 内で note 投稿を完了させた
後で Sheets 行の status を ✅投稿済み に更新する。投稿後 → status 更新の間で kill すると
note 側だけ post 済みになり Sheets は再 publish 候補として残る。

**対策 (当該分削除済 / 恒久対策未):**
- 削除: `scripts/_delete_old_paid_dupes.py` で旧 URL を delete_article 経由で削除
- 恒久 (検討中):
  - publish 開始時に note 側 ダッシュボードを走査して「直近30分の未トラック URL」
    が無いか事前チェック
  - もしくは publish 前に Sheets に「PUBLISHING」中間 status を持たせて、kill 時の
    残骸を検出可能にする
  - **bulk_approve 前に必ず note ダッシュボードと Sheets を照合する SOP**

**How to apply:** publish を kill したら、次回 publish 前に必ず note ダッシュボードを
開いて未トラックの新規 URL が無いか確認。orphan を見つけたら `_delete_old_paid_dupes.py`
パターンで削除する。

---

## 2. edit_article 有料記事 → 「有料エリア設定」ステップ欠落

**事象:** 2026-05-14 publish 済 paid 記事を edit_article で更新しようとして
「更新ボタンが見つかりません」で FAIL。実際は note 側で本文も保存されておらず、
**実体は本当の失敗**。

**原因:** note の編集フローは有料記事と無料記事で UI が分岐する:
- 無料: 公開設定 → 更新する
- 有料: 公開設定 → **有料エリア設定** → 更新する

既存コードは「更新する」を探していたが、有料記事の中間ステップ「有料エリア設定」
を踏まないと「更新する」ボタンの画面に遷移しない。

**対策 (実装済み):**
- `publishers/note_publisher.py` edit_article() に「有料エリア設定」「button:has-text」
  セレクタを追加。無料記事ではセレクタが空ヒットして no-op。
- 関連 commit: `c930dca`

**How to apply:** edit_article で update fail を観察したら、まず paid-flow の中間
ステップが正しく踏まれているか note_edit_failed.png スクショで確認。

---

## 3. ChatGPT image gen → MD5 同一画像 (note logo) を 11連

**事象:** 2026-05-14 paid 記事の cover + inline 11枚を ChatGPT 画像 gen で生成した
ところ、**全 11 枚が byte-identical (md5: cb5a590d10b36bffb60fd8bbb29f44a5、23618 bytes)** で、
中身は note.com の黄色矢印ロゴ的なアイコン画像だった。

**原因 (二段):**
1. ChatGPT サイトが Cloudflare Turnstile challenge を挿入したが、
   `chatgpt_image_generator._install_navigation_guard` の allowlist に
   `challenges.cloudflare.com` が無く、challenge iframe が abort されていた。
   結果、composer が load されず、画像 URL 検出器が page 上の謎のアイコン img を
   pick し続けた。
2. launch_persistent_context の `_start_new_chat()` は同じ chatgpt.com URL に
   goto するだけで、実際には新規 chat にならず前 chat の画像が残ったまま
   `_wait_for_image()` が動いた。

**対策 (実装済み, gate 層):**
- `_ALLOWED_HOSTS` に `challenges.cloudflare.com` を追加 (commit `e94791c`)
- `_download_via_browser` に「PNG が 50KB 未満なら placeholder と判定して raise」追加
- 当面は **Pillow banner fallback** (`scripts/_pillow_banner_paid_2.py`) を使用

**How to apply:** ChatGPT image を batch で取得した時、md5sum が複数枚で同一になって
ないか check。同一なら ChatGPT 側の challenge / composer 失敗を疑う。
**Pillow banner で代替可能 (確実)。**

---

## 4. `rotation_weight=0` が 0.01 で floor される

**事象:** 2026-05-14 ユーザーが「赤羽名店トピックはもういい」と指示 → seed の
`rotation_weight` を 5.0 → 0.0 に下げたが、次回 generate でも依然として赤羽が
note トップ候補に選ばれてしまった。

**原因:** `collectors/knowledge_topics_collector.py` の weighted sampling 内で
`max(float(r.get("rotation_weight") or 1.0), 0.01)` がデフォルト floor として
0.01 を強制適用していた。「typo で 0 にしても抑止しない」防御が、意図的な disable
を無効化していた。

**対策 (実装済み):**
- 同ファイルに「`rw ≤ 0` または `disabled_reason` セット時は eligible から完全除外」
  ロジック追加
- 加えて cross-session-portable な `config/knowledge_topic_excludes.yaml` を新設
  (data/knowledge_topics.json は gitignore なので)
- 関連 commit: `77919df`

**How to apply:** topic を完全に止めたい時は seed の `rotation_weight: 0` だけでなく
`disabled_reason` も書く + `config/knowledge_topic_excludes.yaml` に ID を追記する。

---

## 5. Sheets 不合格 cooldown の timestamp parse 失敗

**事象:** 2026-05-14 不合格題材を 24h cooldown するロジックを新規追加したが、
実際には cooldown が一切発火せず、TikTok/Lake Tahoe/Utah 等が generate 候補に
浮上し続けた。

**原因:** Sheets が timestamp セルを **表示時に整形** する: `2026-05-14T08:34:49` を
保存しても `get_all_values()` は `2026-05-14 8:34:49` (single-digit hour, no T) を
返す。Python `datetime.fromisoformat()` は single-digit hour を rejects。
parse 失敗した行は cooldown 対象から落とされていた。

**対策 (実装済み):**
- main.py `_recently_rejected_titles` に `strptime` 多形式 fallback 追加:
  `%Y-%m-%dT%H:%M:%S.%f` / `%Y-%m-%dT%H:%M:%S` / `%Y-%m-%d %H:%M:%S` / `%Y-%m-%d %H:%M`
- 関連 commit: `77919df`

**How to apply:** Sheets API の timestamp 取得結果は **常に整形されている** と仮定し、
fromisoformat 一発に依存せず strptime fallback を併用する。これは Sheets 全般のパターン
として記憶。

---

## 6. Writer Gemma3 が `## H2` 構文を ~50% で守らない

**事象:** 2026-05-14 generate 6 連発で、note 記事の見出しが `**1. heading**`
(太字段落) として出力され、`##` markdown H2 として認識されないため
`objective_scorer.heading_structure` (≥2 H2 必須) で連続 reject。Writer prompt に
明示的な ## 指示を追加しても改善せず、Gemma3 の compliance 問題と判明。

**原因:** Gemma3 12B の instruction-following は news 系の deep_dive テンプレートで
50% 程度しか markdown H2 を守らない。プロンプト強化だけでは改善しない。

**対策 (実装済み):**
- main.py に deterministic な post-processor `_fix_bold_pseudo_headings()` を追加:
  `^\*\*\d+\.\s+...\*\*\s*$` 形式の太字を `## N. ...` に置換 (line-anchored、char-safe)
- 効果実証: Lake Tahoe (1→8 H2), Utah (1→6 H2)
- 関連 commit: `3056fa0`

**How to apply:** prompt-level の syntax 強制は LLM compliance の弱点を補えない。
post-processor で deterministic に変換する。同パターン (markdown 構造) は他にも
出る可能性大 → similar fix を検討。

---

## 7. Writer が短いソース → 一般解説に Scope Drift

**事象:** 2026-05-14 generate で、Lake Tahoe 住民 5万人電力喪失ニュース →
「Lake Tahoe 観光ガイド」に変質。Utah datacenter 反対ニュース → 「Stratos プロジェクト
バランス解説 + 架空の BYU/J&J 担当者引用」に変質。両方とも元ソースの主題と無関係。

**原因:** Writer (Gemma3) は短いソース記事を補強するときに「2800字目標」要件を
満たすため、勝手に題材を広げて一般解説に逃げる傾向がある。同時に、架空の引用
(肩書きベース)・架空の数値で字数を埋める。

**対策 (実装済み, prompt 層):**
- prompts.yaml `note_article_prompt` + `zenn_article_prompt` の整合性ルールに以下追加:
  - 数値ファクト捏造禁止 (例: Lake Tahoe 1645m 誤記)
  - 架空の人物・組織からの引用禁止 (Utah BYU 等の事例)
  - 元記事のスコープから逸脱しない (Lake Tahoe 観光化禁止)
- 関連 commit: `77919df`, `c930dca`

**How to apply:** これは prompt 層の対策のみ。Writer compliance が弱い場合
(Gemma3 で実証済) は **rescue/expand 時に検証済ファクトを inline で再注入** する
セカンドパスが効果的。`scripts/_rewrite_paid_articles.py` の WASP_FACTS/CISCO_FACTS
パターン参照。

---

## 15. ChatGPT 画像セレクタ漂流 → placeholder → Unsplash 連発

**事象:** 2026-05-15 note 3 記事 publish 時、ChatGPT 画像生成が cover + inline
を全部 23,618 byte の同一 placeholder (note カスタム GPT アプリのアイコン) で
返し、size guard が弾いて全画像が Unsplash 写真 fallback になった。ユーザーの
「文字入りインフォグラフィック画像」要望と乖離。

**原因:** `chatgpt_image_generator.py` の生成画像取得セレクタが
`[data-message-author-role="assistant"]` を使用していたが、ChatGPT が UI を
変更し現行 DOM は `[data-testid^="conversation-turn"]`。旧セレクタは 0 ヒット
→ assistant turn が見つからず `document` 全体に fallback → サイドバーの
カスタム GPT「note」アプリのアイコン (512×512、生成画像と同じ
`backend-api/estuary/content` host で配信、`avatar|icon` トークン無し) を
誤取得。さらに `naturalWidth=0` の生成直後画像をサイズフィルタで弾いていた。

**対策 (実装済み):**
- ターン特定を `[data-testid^="conversation-turn"]` に変更 (旧 role セレクタは legacy fallback に降格)
- placeholder 排除を `!closest('nav')` に一本化 (カスタム GPT アイコンは全て nav 配下)
- `naturalWidth=0` の若い画像を捨てず、レイアウト幅優先 + ロード済み優先ソート
- 単体テスト `scripts/_test_chatgpt_image_fix.py` で実画像 2.2MB download を確認
- **画像パイプラインを RAG に配線**: `chatgpt_batch_helper._log_image_failure_incidents`
  が ChatGPT batch 重大失敗 (cover 無し / inline 過半数失敗) 時に `ops_incidents` を
  query して `[ops-banner:image]` 警告を出す。従来 RAG は本文生成と publish バナーに
  しか配線されておらず、画像失敗知識が活きていなかった

**How to apply:** ChatGPT 画像が placeholder / 小サイズばかりになったら、まず
ChatGPT の UI 変更を疑う。DOM セレクタ (`conversation-turn` 等) が現行と一致
するか `scripts/_diag_chatgpt_cdp.py` で確認。ChatGPT は UI を予告なく変える
ので、セレクタは陳腐化する前提で扱う。

---

## 16. Phase 2 で forbidden regex の catastrophic backtracking → 30分ハング

**事象:** 2026-05-15 generate の Phase 2 で、ある記事のスコアリング中に
プロセスが 30分以上 CPU 100% で沈黙。Ollama も idle、ログも進まない。
runs 19・20 で再現。

**原因:** `config/settings.yaml` の AI 接続詞検出 regex
`そのため(?:[^。]{0,80}。[^そ]{0,300}){2,}そのため` が nested bounded
quantifier を持ち、gemma4:e4b の 7-8k 字出力 (接続詞多用) に対し
catastrophic backtracking を起こした。`objective_scorer._score_forbidden_phrases`
の `re.findall` が C 拡張内で GIL を握ったまま指数時間。

**対策 (実装済み):**
- `settings.yaml` / `.example` の 3 regex を 1段 quantifier の線形形
  `(?:そのため[^。]{0,400}。\s*){3,}` に書換 (意図「3連発検出」は不変)
- `objective_scorer._score_forbidden_phrases` に接続詞 count gate
  (`article.count(接続詞) < 3` なら regex skip) + per-pattern timing log

**How to apply:** forbidden_phrases / sanitizer の regex に
`(?:...{0,N}...{0,M}){2,}` 形の nested quantifier を絶対に書かない。
線形マッチで表現する。新規 regex は長文 (8k字) でタイミング検証する。

---

## 17. RAG retriever が記事ごとに SentenceTransformer 再生成 → HF Hub ハング疑い

**事象:** 2026-05-15 generate の Phase 2 で沈黙ハング。kill 時に AWS / Google
向け TCP が CloseWait 状態で残存。

**原因 (疑い):** `rag_retriever.py` が記事処理ごとに `SentenceTransformer` を
fresh インスタンス化し、その都度 HF Hub に ETag / HEAD チェックを発行。
HF Hub の CDN への接続が CloseWait のまま read を待つ疑い。なお真因は
incident 16 (regex backtracking) の方だったが、HF Hub への不要な通信は
独立した問題として残る。

**対策 (実装済み):**
- `.env` に `HF_HUB_OFFLINE=1` `TRANSFORMERS_OFFLINE=1` `HF_HUB_DOWNLOAD_TIMEOUT=30`
  を設定。embedding / reranker モデルは既にローカル cache 済なので、HF Hub への
  round-trip を完全に止める。「外部 API 利用ゼロ」要件とも一致

**How to apply:** RAG / embedding モデルは初回 `build_rag_index.py` 実行時のみ
online 取得。以降は `HF_HUB_OFFLINE=1` で cache 専用。SentenceTransformer の
module-level キャッシュ化 (記事ごとの再生成をやめる) は恒久対策として未実施。

---

## 18. note 記事が見出しだけから生成され、全引用が捏造される

**事象:** 2026-05-17、28th generate の note 4 記事 (Bill to block publishers /
Xbox rebrand / History of IDEs / Motorola Razr Fold) を内容濃度評価したところ、
本文中の `> "..."` 引用ブロックが**すべて捏造**。元ソースに存在しない英語の
文をでっち上げて媒体名を付与していた。記事自体も元ソースの固有名詞・数値・
5W1H をほぼ含まず、抽象的な処世訓で字数を埋めた「タイトル負け」状態。
25th–27th の publish 済み note 記事 (計 8 本) も同じ経路で生成されている。

**原因:**
- note 記事のネタ元は Reddit (`r/technology` / `r/programming`)。これらは
  **リンク投稿**で `reddit_collector.py` は `post_data["selftext"]` (= 空文字列)
  を `content` に入れる。リンク先記事の本文は一切取得していなかった。
- 本来 note の grounding は `_codex_research_brief` (Codex CLI web 検索) が担う
  設計だが、`.env` で `CODEX_RESEARCH_ENABLED=false` (API 課金回避) + 
  `NOTE_ALLOW_NO_CODEX_BRIEF=1` (fail-closed gate バイパス) になっており、
  grounding が完全に無効。
- 結果、Writer (gemma4:e4b) は `note_article_prompt` の `【本文抜粋】{content}`
  が空のまま、**タイトル ({title}) と URL だけ**を見て 5000 字超を生成 →
  引用も事実も全部 LLM の創作。objective_scorer は元ソースのドメイン
  (arstechnica/theverge) が Tier1 なので evidence_level=A を付け、citation_format
  緩和ルール (URL 不問で 2+ 引用なら B) が捏造引用を素通しさせていた。

**対策 (実装済み, 2026-05-17):**
- `main.py` に `_fetch_article_text(url)` を追加 — requests + BeautifulSoup で
  リンク先記事の `<article>`/`<main>` 内 `<p>` を抽出 (重複段落除去, 6000字 cap)。
- `main.py` に `_backfill_source_content(article)` を追加 — `content` が
  `_MIN_SOURCE_CONTENT_CHARS` (400) 未満かつ非 reddit の http URL があれば
  リンク先本文を取得して `article["content"]` を埋める。
- `_generate_single_article` の grounding gate を「Codex brief **または**
  source body のどちらか」で grounded 判定するよう変更。両方欠落時のみ
  fail-closed (従来は Codex brief 単独で判定)。

**How to apply:** 新しい収集ソースを足すときは `content` が実体を持つか必ず
確認する。リンク集約系 (Reddit / HN / はてブ) は投稿本文が空になりがちで、
本文取得 backfill を通さないと Writer が全捏造する。`{content}` が空のまま
LLM に渡る経路を作らない。publish 済み 25th–27th 記事は事後修正不能、
grounding 修正後に再 generate した記事で置き換える方針。

**検証 (2026-05-17):** 同じ 4 トピックを `scripts/_regen_28th_test.py` で
backfill 修正ありで再生成。全 4 記事で本文中の引用・固有名詞・数値が
ソースに実在することを確認 (Bill: Protect Our Games Act / Monitz Katzner /
60日通知 / The Crew、Xbox: Asha Sharma の X 投票、IDEs: Jeff Dean 帰属 +
2011/2013/2020/2021 + Cider/VSCode、Razr: 10.1mm/IP49/6,200nit/pOLED —
すべて一次ソースに FOUND)。**学び: gemma4:e4b はソース本文さえあれば逐語
引用しスコープも守る。捏造は「モデル能力」ではなく「入力欠落」が原因
だった** — prompt/model をいじる前に入力 grounding を疑うこと。
副次効果: `subj_evaluator` の `research_brief` (main.py: `article["content"]`)
にも実ソースが渡り、accuracy 検証が機能するようになった。

---

## 運用ルール

### 新事故時の手順

1. **本ファイル末尾に「## N. タイトル」セクションを追加** (事象 / 原因 / 対策 / How to apply)
2. **カテゴリ別サマリ表** に 1 行追加
3. **`py scripts/build_rag_index.py`** で chromadb を再 ingest
4. 関連 commit ハッシュを「対策」に明記してコード追跡可能に

### 既存事故の更新

ステータスや対策が変わったらカテゴリ表 + 該当セクションの両方を更新。memory file との
重複は OK だが、**正典は本ファイル** (memory は point-in-time 観測、本ファイルは現在
状態と対策)。
