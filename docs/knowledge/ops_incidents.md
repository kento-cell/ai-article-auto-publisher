# 運用インシデント・レジストリ

_最終更新: 2026-05-14_

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
