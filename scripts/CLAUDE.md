# Scripts — Compound Workflow Playbook + カタログ

scripts/ 配下を触った時のみロード。 ユーザーの自然言語指示 →
スクリプト実行手順の正規化マッピング。

## 命名規則

- `_` (underscore) prefix = **一回限り / 状況限定の one-shot**
- prefix 無し = 継続運用 (もし one-shot から定常化するなら prefix を外す)

## 🎯 Compound Workflows

### 1. 「ジェネレートして全部承認してパブリッシュ」

```bash
PYTHONIOENCODING=utf-8 py main.py --generate            # 収集→生成→Sheets登録
PYTHONIOENCODING=utf-8 py scripts/_bulk_approve_sheet.py   # 全行 ✅承認 に
PYTHONIOENCODING=utf-8 py scripts/_publish_free_first.py --free-first 0
# ↑ note は全部 paid、 zenn は queue 投入
```

### 2. 「無料 N 本 + 有料 M 本」 (note のみ)

```bash
PYTHONIOENCODING=utf-8 py scripts/_publish_free_first.py --free-first 2
# note 4 本承認なら 2 free + 2 paid。 zenn は queue 投入
```

### 3. 「ALL FREE」 (note 全件 ¥0)

```bash
PYTHONIOENCODING=utf-8 py scripts/_publish_free_first.py --free-first 999
```

### 4. 「スクラップ記事投稿」 (data/scraps/ の未公開ドラフト)

```bash
PYTHONIOENCODING=utf-8 py scripts/_publish_pending_scraps.py --limit 10
PYTHONIOENCODING=utf-8 py scripts/_publish_pending_scraps.py --limit 10 --max-age-hours 168
```

判定: `data/articles/{aid}.json` の `published_url` 空なら未投稿。

### 5. 「画像を ChatGPT で生成し直して」

```bash
# 直近 4 本 (TARGETS 編集可)
PYTHONIOENCODING=utf-8 py scripts/_regen_today_note_with_chatgpt.py
```

任意の最近記事には `scripts/fix_recent_note_images.py` (Unsplash) or
`scripts/regen_eyecatch_with_chatgpt.py` (cover のみ)。

### 6. Brave CDP モード (Brave 開きっぱで ChatGPT 画像生成)

```bash
scripts/launch_brave_cdp.bat
# .env の CHATGPT_CDP_PORT=9222 が読まれて connect_over_cdp で attach
# launch_persistent_context は CDP 失敗時の自動 fallback
```

## 📜 Scripts カタログ

### one-shot (`_` prefix)

| script | 用途 |
|--------|------|
| `_bulk_approve_sheet.py` | Sheets ⏳承認待ち を batch_update で一括 ✅承認 (guard なし版) |
| `_publish_free_first.py` | `publish_approved` を呼ぶ。 `--free-first N` で note 最初 N 本だけ ¥0 |
| `_publish_pending_scraps.py` | data/scraps/*.md の未投稿ドラフトを ZennScrapPublisher で投稿 |
| `_publish_prompt_book_to_zenn.py` | 2026-05-28、 _prompt_engineering_book.md を Zenn article 化 |
| `_regen_today_note_with_chatgpt.py` | 直近 publish 4 本に ChatGPT 画像で cover+inline 再生成 → edit_article 差し替え |
| `_regen_5_28_note_images.py` | 2026-05-28、 poster route 付き 4 件 regen (K-beauty 雑誌調) |
| `_regen_5_28_standard_only.py` | 5-28 staticmethod gotcha 修正後の 2 件 rerun |
| `_purge_chatgpt_sidebar.py` | 画像生成で leak した ChatGPT chat を soft-delete |
| `launch_brave_cdp.bat` | Brave を `--remote-debugging-port=9222` で起動 |

### 定常運用 (prefix 無し)

| script | 用途 |
|--------|------|
| `bulk_approve.py` | グレード C / SNS hallucination guard 付き bulk approve |
| `fix_recent_note_images.py` | note 既存記事のインライン Unsplash 差し替え |
| `regen_eyecatch_with_chatgpt.py` | note 既存記事の eyecatch だけ ChatGPT で差し替え |
| `publish_scraps_as_articles.py` | scrap を full article として publish (queue 中は遅延) |
| `analyze_performance.py` | quality_anti_patterns / quality_successes 自動再生成 |
| `test_hallucination_deny.py` | 40 deny + 7 sanitizer + 3 RAG cases regression test |

## ChatGPT 画像 batch の落とし穴

- **cover を style 化したい時は monkey-patch せず `style_preset` を使う**
  (2026-06-01 汎用化)。 `chatgpt_image_batch(..., style_preset="kbeauty_poster")`
  → preset の `cover_styled=True` で cover も infographic banner ではなく
  style_block 準拠になる。 preset 定義は `generators/image_style_presets.py`。
- `ChatGPTImageGenerator._build_prompt` は @staticmethod。 万一 monkey-patch
  する時は `cls.__dict__["_build_prompt"]` で descriptor object を取得して復元。
  `cls._build_prompt` (attribute access) は unwrap して bare function を返し、
  bare function を class attr に書き戻すと instance method 化 → `self` が
  positional arg 1 として渡って引数衝突する (2026-05-28 実証)
- per-image session policy: 画像 1 枚ごとに new chat、 完了後即 soft-delete
  (sidebar leak 防止)。 失敗パスでも cleanup される設計
