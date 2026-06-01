# Publishers — 既知の罠と運用注意

このディレクトリは Zenn / note / Gmail / Slack への投稿を扱う。 ロード
は「publishers/ 配下を read/edit した時に限定」。 詳細手順は
`docs/sessions/STATE.md` の Pointers から辿る。

## 🚧 Zenn = slow-walk publish queue (旧"cap" は誤診断)

- 旧 memory「2026-04-15 以降 push 全部 silently 404、 原因未解明」 は **誤診断**
  (2026-05-28 訂正)
- 実態: account-level の publication rate limit、 1 article / 2-3 日ペース、
  push 自体は通る、 表示は 6 週間遅延
- 確認: `curl -s "https://zenn.dev/api/articles?username=zenn-user&order=latest&count=5"`
- `publishers.zenn_publisher.publish()` が False を返す時は cap ではなく
  ローカル git 問題 (auth / upstream 未設定 / merge conflict) を疑う
- 詳細: memory `project_zenn_cap_blocked`

## 🚧 note `_set_price` の price input 不可視 (2026-05-13)

- ¥300 default で進行する false-path がある (UI セレクタ漂流)
- determine_price 表で B+B = ¥300 なので一致するケースが多いが、 A+A の
  ¥1980 articles でも ¥300 で publish されると損失
- 検証: publish 後に note ダッシュボードで価格確認、 間違っていれば edit で修正

## 🚧 note membership-add (2026-06-01 再診断: selection-mode と判明)

旧バグ「クリエーターページ リンクが見つからない」は avatar→creatorページ遷移の
破綻。正しいフロー (live DOM 確認済、 `_apply_membership_fix.py` で実装):

```
自分の記事 /notes → 記事行の ⋮ (button[aria-label='その他'])
  → balloon の「メンバーシップ特典追加・解除」
  → /notes が【選択モード】化:
       各記事に input.a-checkbox__field (slug で特定: .o-articleList__item
         :has(a[href*='/n/<slug>']))
       右ペインに【プラン別「追加」ボタン】(<a class=a-button>)
       現状プラン2つ:「メンバー全員に公開」(全員向け汎用) /「有益なAIプラン」(AI特化)
  → 対象記事チェック → 目的プランの「追加」で確定
```

`NotePublisher.add_articles_to_membership(slugs, plan_name)` に書き換え済
(navigation + slug 特定 + ticking は動作確認)。K-beauty/一般記事は
「メンバー全員に公開」へ。

**未解決の壊れやすさ**: JS で hidden input をトグルすると選択モードが崩れる
(Vue の選択状態に登録されずプラン「追加」ボタンが消滅 → 確定不可)。
real-gesture click (可視 `.a-checkbox__check` を実クリック) が要る可能性。
**エンドツーエンド自動追加は未達 → 当面は手動追加が確実**。best-effort なので
publish 自体は成功。累計 backlog は STATE.md 参照。

## 🚧 edit_article の「更新ボタンが見つかりません」 FAIL は false negative

- 2026-05-13 実証: FAIL を返しても note 側では大半保存されている (og:image
  更新済)
- FAIL ログ無視して `curl` / og:image 確認で真偽判定

## 🚧 note 本文画像は CDN re-host 必須

- ProseMirror エディタは `assets.st-note.com/img/` 配下の画像しか描画しない
- 外部 URL (Unsplash etc.) は黙って描画せず、 ソース markdown が plain text
  として表示される
- 必ず `inline_image_paths` 経由でローカルファイルをアップロードする
  (`_drop_local_images` ルート、 `_strip_local_images` ではない)
- 詳細: memory `project_note_inline_image_flow`

## 借用画像ポリシー (2026-05-27 配線)

- 第三者画像 (公式 SNS 等) を本文に置いた記事は paid 化禁止 (price=0 強制)
- detection: `main.py::_has_borrowed_image_attribution` が「画像をお借りしました」
  「Photo via」 「© 」 等 9 種 marker を検知
- stock 画像 (Unsplash / Pexels / ChatGPT 生成 / Pillow バナー) は paid 可
