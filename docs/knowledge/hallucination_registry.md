# ハルシネーション事故レジストリ — 集約版

_最終更新: 2026-05-14_

過去に観測されたハルシネーション事故を 1 ファイルに集約し、
**事象 → 原因 → 対策(deny) → ステータス** の形式で追跡する。
新規事案は本ファイル末尾に追記し、原因が同じものは既存項目を更新する。

このファイルは「対策が機能しているか」を継続的にレビューするための
プライマリインデックス。個別の修正コミットや関連 memory はリンクで参照する。

---

## カテゴリ別サマリ

| #  | カテゴリ                  | 観測日       | コード対策                                            | ステータス |
|----|---------------------------|--------------|-------------------------------------------------------|------------|
| 1  | 架空 SNS 投稿引用           | 2026-04前半 | settings.yaml `forbidden_phrases` (Bluesky/Threads/Mastodon) + main.py `_PUBLISH_DENY_PATTERNS` | ✅ 修正済 |
| 2  | 架空ニュースイベント        | 2026-04-22   | settings.yaml `forbidden_phrases` (トレンド入り/話題/賛否) | ✅ 修正済 |
| 3  | プロンプト残留 placeholder  | 2026-04-23   | content_sanitizer.py + settings.yaml + URL allowlist | ✅ 修正済 |
| 4  | 「〇〇/×× 等」未置換伏字    | 2026-04-23   | settings.yaml + sanitizer (今回の追補で publish-time 強化) | ✅ 修正済 |
| 5  | A/B/C 記号命名で架空店      | 2026-04-23   | settings.yaml `(?:店舗\|ブランド\|...)[ABC]`            | ✅ 修正済 |
| 6  | URL ハルシネーション (店舗) | 2026-04-13   | url_cleaner.py allowlist + Google Places verifier     | ✅ 修正済 |
| 7  | チェーン店混入              | 2026-03〜    | settings.yaml `chain_blacklist` + objective_scorer    | ✅ 修正済 |
| 8  | arXiv 論文 citation_format C | 2026-04-15  | objective_scorer.py auto-credit (arxiv URL → with_url) | ✅ 修正済 |
| 9  | 画像 ハルシネ (alt 不一致)   | 2026-04-30   | main.py `_THEME_KEYWORDS` 順序 + `_ALT_RED_FLAGS` + `_QUERY_SUBJECT_VOCAB` | ✅ 修正済 |
| 10 | 画像 商標違反 (スタジオジブリ) | 2026-04-30 | image-prompt 直接ジブリ言及禁止                        | ✅ 修正済 |
| 11 | 画像プロンプトのキャラ偽装   | 2026-05-01   | image_generator: positive subject vocabulary gate     | ✅ 修正済 |
| 12 | 伏字店名 + AI 開示 footer 残留 (実害) | 2026-05-07   | AI開示 footer 自動削除 + 伏字 publish-deny | ✅ 修正済 |
| 13 | `_ensure_ai_disclaimer` 無条件付与 (26 公開記事に「AI が構成」混入) | 2026-05-08 | gate 化 + 文面差替 + scripts/strip_ai_disclaimer_from_published.py | ✅ 修正済 (live edit はユーザー承認待ち) |
| 14 | 仮名/仮称マーカーで逃げる伏字  | 2026-05-08   | settings.yaml + main.py に（仮名）/（仮称）/ダッシュ伏字追加 | ✅ 修正済 |
| 15 | 回帰テスト suite 完備     | 2026-05-08   | scripts/test_hallucination_deny.py (40 deny + 7 sanitizer ケース) | ✅ 完備 |
| 16 | 架空大学・組織からの引用捏造 | 2026-05-14   | prompts.yaml に「肩書きベース引用」全文却下ルール追加 (zenn + note 両プロンプト) | ✅ 修正済 (prompt層) |
| 17 | ソース外の数値ファクト捏造  | 2026-05-14   | prompts.yaml に「元ソース未記載の数値は書かない」ルール追加 (例: Lake Tahoe 1645m 誤記) | ✅ 修正済 (prompt層) |
| 18 | 見出しを `**bold**` で代用し H2 count フェイル | 2026-05-14 | prompts.yaml に「## (H2) 構文必須、太字での見出し代用は全文却下」追加 | ✅ 修正済 (prompt層) |
| 19 | 元記事スコープ逸脱で別物記事化 | 2026-05-14 | prompts.yaml に「元記事の主題から逸脱しない、観光ガイド化禁止」ルール追加 (Lake Tahoe 観光化事案) | ✅ 修正済 (prompt層) |
| 20 | 架空アンケート主張タイトル (【100人に聞いた】) | 2026-06-10 | main.py `_TITLE_BRACKETS` から事実主張型 5 件除去 + forbidden_phrases / `_PUBLISH_DENY_PATTERNS` 3 箇所同期 `\d+人に聞いた` + 公開済み zenn scrap live 修正 | ✅ 修正済 (詳細 ops_incidents #21) |

---

## 1. 架空 SNS 投稿引用 (Bluesky/Threads/Mastodon)

**事象:** 2026-04 前半に習近平/妻夫木聡/李在明/メッツ/辻希美 etc. の
「〇〇氏の Bluesky 投稿」をでっち上げる事故が頻発。招待制・新興 SNS は
公式認証アカウントが少なく、Gemma3 が Trends キーワードから架空投稿を
作りやすい。実害として 2026-04-22 に「李在明氏の Bluesky 投稿」記事を
公開してしまい撤回。

**原因:** ニュース系トピック生成時、LLM が「投稿の文面」を本文に
書き起こしてしまう。X/Instagram の方は公式認証アカウントが豊富で
URL 検証が機能するが、Bluesky/Threads/Mastodon は弱い。

**対策 (実装済み):**
- `config/settings.yaml` `evidence.forbidden_phrases`:
  - `氏の\s*(?:Bluesky|Threads|Mastodon)\s*投稿`
  - `(?:Bluesky|Threads|Mastodon)\s*投稿が話題` 等 6 パターン
- `main.py` `_PUBLISH_DENY_PATTERNS`: 公開時にも同一チェック (ラスト・ライン・オブ・ディフェンス)
- X/Instagram は除外 (公式認証 URL 検証が機能するため)

---

## 2. 架空ニュースイベント / 架空トレンド入り

**事象:** 2026-04-22 「Vogue Korea のあの号がトレンド入り」「賛否両論交錯」
等、検証不能なバズ事象を断定的に書く。Google Trends のキーワードを
「ハッシュタグがトレンド入りし、議論を呼んでいます」に変換する典型パターン。

**原因:** Trends キーワードはタイトル候補にすぎないが、Gemma3 が
「導入として話題性を煽る」よう学習されており、根拠なく断定する。

**対策 (実装済み):**
- `forbidden_phrases`:
  - `(?:#xxx)がトレンド入り` / `ハッシュタグ.*がトレンド入り`
  - `大きな話題を呼んでいます`
  - `議論を呼んで(?:い|います)`
  - `多くのメディアが.*特集`
  - `賛否両論が.*交錯`
- Trends 由来は `_citation_exempt = {google_trends, bluesky, reddit}` で
  citation_count 非ブロッキング (構造的に弾けない引用要件) だが、
  本文の煽り文面は forbidden_phrases で必ず弾く設計。

---

## 3. プロンプト残留 placeholder (`ここに入力` / `URLは記載しません`)

**事象:** 花澤香菜・令和ロマン記事 (2026-04-23) で、参考リンクに
`(※ 実際には〇〇の公式 URL をここに入力)` がそのまま残った。

**原因:** Gemma3 がプロンプト内の「URL がない場合は省略」指示を理解せず、
「URL は記載しません」「ここに入力」を本文に書き出してしまう。

**対策 (実装済み):**
- `generators/content_sanitizer.py`:
  - `_LINE_KILL_PHRASES = (架空のURL, URLは記載しません, ここに入力, 実際には, (※, （※)`
  - 該当行を丸ごと削除して scorer/publisher に渡る
- `forbidden_phrases` にも同一パターン (sanitizer で取りこぼした場合の保険)
- `prompts.yaml` ケース A/B 分岐: 「URL が手元にない場合は参考リンク
  セクション自体を出力しない」を厳守

---

## 4. 「〇〇/×× 等」未置換伏字

**事象:** 「管理栄養士が警告！SNS で話題の『〇〇ダイエット』」(2026-04-23)
で、本来固有名詞を入れるべき箇所が伏字のまま残る。さらに 2026-05-07 に
「東京 一人飯カウンター」記事で `○○寿司 / ××焼鳥 / □□ラーメン /
△△バル` が**全店伏字**で公開される実害発生。

**原因:** 

- LLM が実在店を特定できず、テンプレ的に伏字で埋める
- これは事実不確実性の正直な開示にも見えるが、読者にとっては
  「中身が無い記事」を堂々と出している裏切り行為
- 既存 forbidden_phrases に **〇〇 (3 種) と ×× は入っていたが、□□ や △△ は
  入っていなかった**。○○寿司のように「伏字 + 業態語」の組合せもまだ弱い

**対策:**
- 既存: `forbidden_phrases`:
  - `「〇〇.*」は`
  - `\*\*〇〇`
  - `〇〇ダイエット|〇〇メソッド|〇〇効果`
  - `(?:〇〇|◯◯|○○|△△|××)(?:専門店|ブランド|...|公式)`
- **2026-05-08 追補 (今回):**
  - `(?:〇〇|◯◯|○○|△△|××|□□)(?:寿司|焼鳥|ラーメン|バル|バー|ビストロ|食堂|酒場|割烹|蕎麦|うどん|カレー|カフェ|喫茶)` を追加 → 「○○寿司」「××焼鳥」を確実に弾く
  - `(?:〇〇|◯◯|○○|△△|××|□□).{0,8}(?:寿司|焼鳥|ラーメン|バル|食堂|酒場)` 緩めの保険版も追加
  - `\*\*[〇◯○△×□]{2}` の太字伏字パターン
  - 伏字 + 「店」字で終わる固有名詞風: `(?:〇〇|◯◯|○○|△△|××|□□)[一-龯ぁ-ゔァ-ヶー]{0,4}店\b`

---

## 5. A/B/C 記号命名で架空店

**事象:** 2026-04-23 ダルゴナ事例で「福岡のダルゴナ専門店 A」「専門店 B」、
花澤香菜事例で「韓国コスメブランド A」「ブランド B」「ブランド C」。

**原因:** LLM が実在店を出せないとき、安全策として記号化して逃げる。
が、読者にとっては中身ゼロ。

**対策 (実装済み):**
- `forbidden_phrases`:
  - `(?:専門店|ブランド|ショップ|サロン|クリニック|カフェ|店舗|スポット|メーカー|スタジオ)[ABCＡＢＣ](?![a-zA-Z0-9])`
  - `prompts.yaml`: 「『店名 A』『ブランド B』のような記号名命名は
    実在認定不可、本文ごと削除対象」と明示

---

## 6. URL ハルシネーション (店舗の公式サイト等)

**事象:** 2026-04-13 note 記事で、LLM が公式サイトURLや食べログURLを
それっぽく自分で組み立て、99% 存在しない or 別店に飛ぶ。

**対策 (実装済み):**
- `utils/url_cleaner.py` `_BODY_ALLOW_HOSTS` で本文 URL を allowlist 制
  (bsky.app, google.com, maps.app.goo.gl のみ)
- `utils/places_verifier.py` Google Places API で店名検証 → ヒットしない
  店ブロックは丸ごと削除
- `prompts.yaml`: 「本文に書いてよい URL は元ポスト URL と Google Maps
  検索 URL のみ。住所・営業時間・価格・電話・公式 URL は LLM が一切
  書かない (Places API で後埋め)」

---

## 7. チェーン店混入

**事象:** ご当地グルメ記事に「スターバックス」「鳥貴族」「サイゼリヤ」等の
チェーン店が混入。プロジェクト方針として「個人店・隠れた名店のみ」が
絶対条件。

**対策 (実装済み):**
- `config/settings.yaml` `evidence.gourmet_rules.chain_blacklist`: 28 店
- `objective_scorer.py` `_score_chain_stores`: ヒット 1 件で **強制 Fail**
  (blocking_issues 入り → 自動却下)

---

## 8. arXiv 論文 citation_format C で構造的不合格

**事象:** Pair2Scene 等 arXiv 由来 zenn 記事が citation_format C で却下。
arXiv abstract には参考文献URLが含まれないため、構造的に基準を満たせない。

**対策 (実装済み):**
- `objective_scorer._score_citation_format`: source の URL に `arxiv.org`
  を含む場合、citation block を 1 件 URL-bearing に auto-credit
  (compliance には加算しない、grade B までしか上がらない)

---

## 9. 画像ハルシネーション (alt 不一致)

**事象:** 2026-04-30 公開済 note 16 件で stock photo がハルシネ。最悪例:
- 「休息の 7 分類」記事に "At Rest" 刻印の墓石
- 「東京のロースター 5 店」にミシン画像
- 「K-beauty スキンケア」にソウルの桜

**原因:** `main.py` `_THEME_KEYWORDS` が first-match-wins で、
umbrella キーワード (韓国/AI) が specifics (スキンケア/焙煎) より上に
あった。K-beauty 記事が「韓国」でヒット → Seoul → 桜画像。

**対策 (実装済み):**
- `_THEME_KEYWORDS` を「具体 → 抽象」順に再構成。「韓国」は最後尾 fallback
- `_ALT_RED_FLAGS`: tombstone / sewing machine / VR headset / cherry blossom
  等で alt と article subject の不一致を弾く
- `_QUERY_SUBJECT_VOCAB`: query → expected vocabulary のマッピングで
  positive 関連性を要求

**運用ルール (新ジャンル追加時の必須 3 ステップ):**
1. `_THEME_KEYWORDS` に新ジャンル → 具体的英語クエリを追加 (umbrella 前)
2. 失敗パターンが出たら `_ALT_RED_FLAGS` に追加
3. クエリ語彙を `_QUERY_SUBJECT_VOCAB` に追加 (positive vocab gate)

---

## 10. 画像生成プロンプトの商標違反

**事象:** 2026-04-30 ChatGPT 画像生成プロンプトに「スタジオジブリ風」が
入り、商標問題発生リスク。

**対策 (実装済み):**
- ChatGPT image generator から「スタジオジブリ」を完全削除
- 個人監督名 (宮崎駿、湯浅政明等) で代替

---

## 11. 画像プロンプトのキャラ偽装 (positive subject gate)

**事象:** 2026-05-01 タイトル「韓国コスメ」記事で生成プロンプトが
「Korean traditional landscape」になり、桜画像が生成される再発。

**対策 (実装済み):**
- 9 と同じ `_QUERY_SUBJECT_VOCAB` で gate

---

## 12. 伏字店名 + AI 開示 footer 残留 (実害事故 2026-05-07)

**事象:** https://note.com/note-user/n/n0647c5e8f8eb (元バージョン) で
4 店舗が `○○寿司 / ××焼鳥 / □□ラーメン / △△バル` の**全店伏字**で公開。
さらに記事末尾に AI による生成である旨の開示 footer がそのまま残留。
2026-05-07 にユーザー指摘で発覚。リアル 9 店に書換完了。

**根本原因:**
1. 既存 `forbidden_phrases` の伏字パターンに「業態語との組合せ」が
   入っていなかった (「〇〇寿司」がスルー)
2. AI 開示 footer (「※本記事は AI で生成しました」「免責事項」等) が
   forbidden phrase として登録されていなかった
3. publish 時の最終 deny check でも捕まらず、本番投稿された

**対策 (本コミット):**

### 4-A. settings.yaml 追加 forbidden_phrases

伏字 + 業態語のフルカバレッジ + AI 開示 footer:

```yaml
# 伏字記号 + 業態語の組合せ (○○寿司, ××焼鳥, □□ラーメン 等)
- "(?:〇〇|◯◯|○○|△△|××|□□)(?:寿司|焼鳥|やきとり|ラーメン|バル|バー|ビストロ|食堂|酒場|割烹|蕎麦|うどん|カレー|カフェ|喫茶|ベーカリー|パン|スイーツ|和菓子|洋菓子|焼肉|鉄板|串|天ぷら|うなぎ|寿し|もんじゃ|お好み|ピザ|フレンチ|イタリアン|中華|韓国料理|タイ料理|薬膳|ビアガーデン|居酒屋|ホルモン)"
- "(?:〇〇|◯◯|○○|△△|××|□□)[一-龯ぁ-ゔァ-ヶー]{0,6}店\\b"
- "\\*\\*[〇◯○△×□]{2,}"
- "「[〇◯○△×□]{2,}[^」]{0,16}」(?:が|は|を|に|で)"

# AI 開示 footer / 自動生成バナー (記事品質を毀損し読者を裏切るので公開禁止)
- "本記事は\\s*(?:AI|ChatGPT|Claude|Gemini|GPT|生成AI)[^\\n]{0,30}(?:生成|作成|執筆)"
- "(?:AI|ChatGPT|Claude|Gemini)\\s*(?:による|が)\\s*自動生成"
- "免責事項[:：]?\\s*本記事"
- "本記事の[^\\n]{0,15}(?:正確性|最新性)を保証"
- "AIによって(?:生成|作成|自動生成)された"
```

### 4-B. main.py `_PUBLISH_DENY_PATTERNS` 強化

publish 時に必ず本文末尾 (tail) もスキャンし、伏字+業態語パターン &
AI 開示 footer を **strict block** する。settings 側に頼らず main.py
にハードコードして「外せない」状態にする。

### 4-C. content_sanitizer.py で AI 開示 footer 削除

publish に出る前の段階で自動削除 (forbidden_phrases ヒットによる
記事丸ごと却下を避けるため、軽微パターンは sanitize で除去)。

---

## 13. 「AI が構成」自動付与 footer (2026-05-08 発覚)

**事象:** 全 235 記事をフルスキャンしたところ、**26 件の公開済み note 記事**に
「本記事の店舗・施設情報は、執筆時点の Google Maps 公開データおよび投稿情報を
もとに AI が構成しています…」という disclaimer footer が残っていることが判明。
さらに、これは LLM ハルシネーションではなく **`main.py:_ensure_ai_disclaimer`
が note 全記事に無条件で hardcode 付与していた** 仕様起因の事故。

技術記事 (Figure / Tesla / 1X、Claude Code、MCP、VLA 等) にも「店舗・施設情報は…」
という文脈不一致な開示が付いていた。

**根本原因:**
1. `_ensure_ai_disclaimer(content)` が STORE_BLOCK の有無を見ずに付与
2. disclaimer 文面が「店舗・施設情報」前提で書かれており、tech 記事には
   そもそも文脈がズレている
3. AI 言及 (「AI が構成しています」) が読者への裏切り = 品質の自己否定
4. 既存 deny pattern が「AI が**生成/作成**」しか見ておらず「AI が**構成**」を
   スルー。`AIによって生成` も「構成/編集」変種を捕えてなかった

**対策:**

### 13-A. `_ensure_ai_disclaimer` の gate 化と文面差替

`main.py`:
- `_AI_DISCLAIMER_SENTINEL` を `<!-- AI_DISCLAIMER -->` →
  `<!-- STORE_DATA_DISCLAIMER -->` に変更 (sentinel 自体が AI 言及を含まない)
- `_AI_DISCLAIMER_BLOCK` 文面から「執筆時点の Google Maps…AI が構成しています」
  を削除。「営業時間・価格・メニューは変更される場合があります」だけに圧縮
- `_has_store_blocks(content)` を追加し、STORE_BLOCK_START sentinel が
  存在する場合のみ disclaimer を付与
- 技術記事には自動付与されない (LLM が独自に書いた免責は別途検出)

### 13-B. deny pattern の動詞群拡充

`config/settings.yaml` + `config/settings.yaml.example` + `main.py:_PUBLISH_DENY_PATTERNS` +
`generators/content_sanitizer.py` の 4 箇所すべてで、AI 開示 footer 検出動詞を
`(生成|作成|執筆|書き起こ)` → `(生成|作成|執筆|書き起こ|構成|編集)` に拡張。
英語形式 `Generated by AI` 等も追加。

### 13-C. 既存 26 件の修復スクリプト

`scripts/strip_ai_disclaimer_from_published.py`:
- legacy disclaimer pattern (`<!-- AI_DISCLAIMER -->` + `## ⚠️ 免責事項` +
  AI/ChatGPT/Claude/Gemini/GPT が出る本文) のみを対象に剥がす
- 新 sanctioned form (`<!-- STORE_DATA_DISCLAIMER -->` + `## ご利用にあたって`) は
  保持
- 既定で dry-run、`--apply` で実行
- 1 件あたり 197-223 文字を削除予定

実行はユーザー承認待ち (Brave + NotePublisher で 26 記事を 1 件ずつ
edit_article するため、1-2 時間の安定実行時間が必要)。

---

## 14. 仮名/仮称マーカーで逃げる伏字 (2026-05-08 発覚)

**事象:** 「東京の特定エリア」記事 (未公開) で `居酒屋の隠れ家「□□」（仮名）` のように
**「（仮名）」を明示**して伏字を正当化しようとするパターンを発見。

**原因:** LLM が実在店を出せないとき、「仮名と書けば嘘ではない」とテンプレ的に
逃げる。これは読者にとっては中身ゼロの記事で、ユーザー方針に反する。

**対策:**
- `forbidden_phrases` に `（仮名）`, `（仮称）`, `（架空）`, `（フィクション）` を追加
- ASCII 括弧 `(仮名)` 等にも対応
- ダッシュ伏字 `ーー寿司`, `‥‥焼鳥` も追加 (記号伏字の網羅)

---

## 16-19. 2026-05-14 観測事案 (prompt 層ガード)

**事象 (16) 架空大学引用:** 2026-05-14 generate 中、Utah datacenter 記事で
「Utah State University の専門家は〜と語っている」「Brigham Young University の専門家は」
「J&J Nursery and Garden Center の担当者は」のような肩書きベース引用を捏造。
元ソース (Guardian 系) には該当発言の記載なし。

**事象 (17) 数値ファクト捏造:** 同じく 2026-05-14、Lake Tahoe 記事で
「最大水深 1,645メートル」と記載 (実際は約 501m)。元ソースに水深記載なし。
LLM の「うろ覚え」が混入。

**事象 (18) 見出し誤構文:** Lake Tahoe / Utah 記事で `**1. なぜ今〜**` のように
**太字で見出しを代用**。Markdown H2 (`##`) が 1 個しか無く、客観 H2 count フェイル
(2回連続で同じ題材が同じ落ち方をするほど再現性あり)。

**事象 (19) スコープ逸脱:** Lake Tahoe ソース「住民 5万人が電力喪失」(具体ニュース)
に対し、生成記事は「Lake Tahoe 観光・環境問題総合解説」に逸脱。読者が期待する
具体ニュースが消えた状態で publish 寸前。

**原因 (共通):** 元ソースが短いニュース記事の場合、Gemma3 が
「記事を厚くするために補強する」モードに入り、知らない数値や肩書き引用で
スカスカを埋めようとする。Writer の「最低 2800 字」要件がこれを誘発。

**対策 (実装済み):**
- `config/prompts.yaml` の zenn_article_prompt / note_article_prompt 両方の
  `【整合性ルール — 違反は即不合格】` ブロックに以下を追加:
  - 「数値ファクトの捏造禁止」(事象 17)
  - 「架空の人物・組織からの引用は絶対禁止」(事象 16)
  - 「見出しは必ず ## (H2) / ### (H3) 構文を使うこと、太字代用は全文却下」(事象 18)
  - 「元記事のスコープから逸脱しない」(事象 19)
- これらは regex で網羅困難なため、prompt-level guard が一次防御。
  Critic / objective_scorer は二次防御として残す。

**deny pattern 化の検討:** 「○○大学の(専門家|研究者|教授)は」を regex で
弾くアイデアもあるが、Tier1 公式インタビューでの正当な引用も同じ形に
なるため、誤爆リスク高い。今は prompt 層止め。再発したら sanitizer に
「肩書きベース引用 + URL 無し」のヒューリスティック検出を追加検討。

---

## 回帰テスト

`scripts/test_hallucination_deny.py` — **40 件の deny ケース + 7 件の sanitizer
ケース**で全パターンを網羅検証。CI 統合可能。

```
$ py scripts/test_hallucination_deny.py
PASS: all 40 deny + 7 sanitizer cases OK
```

含むケース:
- 伏字 + 業態 11 種 (寿司/焼鳥/ラーメン/バル/カフェ/居酒屋/イタリアン/鮨/+店字/太字/鉤括弧)
- 仮名/仮称/ダッシュ伏字 3 種
- A/B/C 命名 2 種
- プロンプト残留 3 種
- 架空アンケート主張 2 種 (N人に聞いた/N人にアンケート、2026-06-10 追加 → 計 42 deny)
- Bluesky/Threads/Mastodon 3 種
- 架空ニュースイベント 3 種
- AI 開示 footer 7 種 (本記事は/構成/別形/による/注釈型/英語/免責)
- ネガティブ 8 件 (実在店/Claude 技術文脈/A クラス等の正常パターン)

---

## 運用ルール

### deny pattern 追加時の必須チェック

新しい forbidden_phrases を追加するときは:

1. **3 箇所同期確認**:
   - `config/settings.yaml` (scorer 用)
   - `config/settings.yaml.example` (新規開発者用)
   - `main.py` `_PUBLISH_DENY_PATTERNS` (publish ガード — 必要なものだけ)
2. **regex バリデーション**: `python -c "import re; re.compile(r'<pat>')"` で
   不正な regex を弾く (settings.yaml 読み込み時に warning は出るが、
   そのパターンは無視されるので必ず事前確認)
3. **誤爆チェック**: `tests/regex_smoke_test.py` 相当を実行して、
   実在店名や正常な技術用語に誤マッチしないか確認
4. **本ファイル更新**: 観測事例と対策を本ファイルに追記

### memory との関係

個別事故の point-in-time 観測は memory/ に残すが、**「何を deny
すべきか」の正典 (canonical source) は本ファイル**。memory が古くなったら
本ファイルとコードを信用すること。

### Codex cross-review 推奨

deny pattern 追加時は `/codex-review` に投げて誤爆リスクを独立評価して
もらう。特に regex は人間 (Claude 含む) がレビューを誤りがち。
