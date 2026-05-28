# Operations Knowledge — Project-Shared (mirror of user-private memory)

このファイルは canonical な運用知識を git に乗せて、別ユーザー/別マシン/別エージェント
(Claude / Codex / Cursor) でも参照できるようにしたもの。`~/.claude/projects/E--ai-article-auto-publisher/memory/`
にある user-private memory のうち **project に関する事実だけ** を抜粋・転記している。

ユーザー個人の preferences (自走モード許可、スケジューラ拒否など) は memory 側に残し、
ここには「コードを変えても変わらない project の真実」だけを置く。

---

## 1. note 価格設定ポリシー (2026-05-12 メンバーシップ + 有料記事審査通過後)

```python
# publishers/note_publisher.py::determine_price
A + A evidence: ¥1,980
A + B evidence: ¥980
B + A evidence: ¥500
B + B evidence: ¥300
C / fallback:    ¥200  # floor
```

メンバーシップ ¥1,020/月。全記事 paid + メンバー全員に無料公開がポリシー。
publish 後に `_add_to_memberships_via_dashboard` がメンバー特典追加を試みるが、
selector 漂流で 2026-05 以降は failing → ダッシュボードから手動追加。

## 2. Zenn article cap (2026-04-15 以降のブロック)

12 本程度を超えて publish すると git push 自体は成功するが、URL を叩いても
silently 404 が返る。原因不明。`main.publish_approved` は 1 本目で 404 検出
→ `_zenn_cap_exhausted` flag セット → 同 batch の残り全部 scrap fallback。

cap が解除されるまでは:
- `_xp_enabled("publish.zenn_scrap_only", default=False)` で scrap-only モード強制
- または cap-detection の自動 fallback に任せる (推奨)

ユーザーが Zenn ダッシュボードで「公開済み記事 N 本」のうち何本が実際 indexable か
確認するまで article publish は控える。

## 3. note インライン画像フロー (2026-04-18 確認)

```python
# 正解パターン
content = self._drop_local_images(content)   # 本文の ![...](data/images/...) を消す
# その後 _inject_inline_images() で note の paste handler 経由でアップロード
```

`_strip_local_images` (古い実装) に戻すと、本文に raw Markdown が visible text として
表示される (ProseMirror は外部 `<img src=...>` を渡されると render しないため)。

## 4. ハルシネーション 3 層ゲート (2026-04-30 修正)

画像 alt text のハルシネーションを防ぐ:

1. **THEME 順序ルール** — 抽出 keyword から query を生成する優先度
2. **red flags** — 'boat', 'rip' など、記事と無関係な単語が alt にあったら drop
3. **positive vocabulary** — query 由来の語彙が alt に無ければ drop

新ジャンル (グルメ / コーヒー / 韓国 etc.) を追加するときは 3 つ全部更新が必要。
canonical な事故リスト: `docs/knowledge/hallucination_registry.md`

## 5. ChatGPT 画像生成パイプライン

- 中核: `generators/chatgpt_image_generator.py`
- プロンプト: `generators/visual_prompt_builder.py` (Gemma3 が日本語要約を生成)
- 統合点: `chatgpt_batch_helper.chatgpt_image_batch`
- 固定チャット: `data/chatgpt-image-chat-url.txt`

### CDP attach モード (2026-05-13 既定)

`.env` で `CHATGPT_CDP_PORT=9222` を設定 + Brave を `scripts/launch_brave_cdp.bat`
で起動すれば、Brave 開きっぱでも `connect_over_cdp` で attach。
詳細は CLAUDE.md / AGENTS.md の Compound Workflow Playbook 参照。

#### 自動起動 opt-in (2026-05-27 追加)

`.env` に `AUTO_LAUNCH_BRAVE_CDP=1` を入れると、`_publish_note` 内の
`chatgpt_image_batch` が CDP port を probe し、cold なら
`launch_brave_cdp.bat` を自動 spawn する (`ensure_brave_cdp_listening`)。
launcher は `taskkill /F /IM brave.exe` してから再起動するので、Brave を
別作業で使う最中に publish が走ると巻き込み再起動になる。Brave session
restore で tab は戻るが、フォーム入力中などは消える。OFF のままでも、既に
CDP listener が居れば attach、居なければ Pollinations / Unsplash に fallback
する現状動作 — 自動 disrupt しない安全側がデフォルト。

### スタイル: Studio Ghibli 風 (ユーザー指定 2026-04-28)

- cover は強 infographic OK
- inline は弱 infographic OR 普通の絵 (watercolor 系、テキストオーバーレイ控えめ)

### 既知バグ Bug 3 (未修正、2026-05-13 実証)

`edit_article` が「更新ボタンが見つかりません」で False を返すが、note 側では
実際保存されている (`og:image` の更新で確認)。FAIL ログを真に受けず live page で
実態確認するのが正しい運用。

## 6. Sheets duplicate-row bug (2026-04-23 修正済)

`update_status` が first-match 行だけ更新していたため、同じ article_id が複数行
あると republish ループする実害があった (3 回投稿事故)。修正後は全 match を更新。

## 7. PostToolUse フック kill 地雷 (修正済、絶対戻すな)

`post-bash-pipeline.sh` で `Stop-Process` を呼ぶと自身を kill して TaskTimeout 連発。
削除済み。**Stop-Process を絶対に戻さない**。

## 8. RAG 統合 (2026-05-11 完了)

- chromadb + e5-base embedding
- ハルシ防御 + 重複検出 + RAG-prompt + 画像 alt gate に配線済
- `RAG_ENABLED` env var で A/B 計測中
- 詳細: `docs/sessions/archive/_legacy/20260511_*` / `generators/rag_*`

## 9. 即興スクリプト → 即 commit ポリシー (2026-05-13)

ユーザーが compound 指示 (例: 「ジェネレートして承認してパブリッシュ無料 N 有料 M」) を
投げると、その場で wrapper スクリプトを書くことがある。書いたら即 git add + commit、
かつ CLAUDE.md / AGENTS.md の Scripts カタログに追記。

理由: 他セッション (= 別ターミナル / 別マシン / Codex 経由) から同じプロンプトが来たとき
同じスクリプトに辿り着けるように、project-shared 場所に置くのが portability の本質。

## 関連ドキュメント

- `CLAUDE.md` — root universal rules、 詳細は subdir `publishers/` `scripts/` `bot/` の CLAUDE.md
- `AGENTS.md` — Codex / 一般 agent 用、 同じ playbook + 罠を mirror
- `docs/sessions/STATE.md` — current state + Next Actions (≤60 行)
- `docs/sessions/JOURNAL.md` — 今日の append-only log (auto-read しない)
- `docs/sessions/2026-05_archive.md` — 過去 session 履歴 (旧 LATEST.md from rename)
- `docs/knowledge/hallucination_registry.md` — ハルシネーション事故レジストリ (canonical)
- `docs/requirements.md` — 要件定義
- `config/settings.yaml.example` — 48 forbidden_phrases、伏字+業態語、AI 開示 footer
