# Claude Code — AI記事自動生成システム

## ⚡ 自走モード（このファイルを読んだら自動で行動開始）

このリポジトリを開いたら、以下の順に読んで状況を把握し、自走で改修・テストを行うこと。
ユーザーの指示を待たず、LATEST.mdの「Next Resume Actions」に従って動く。

### 起動時の読み込み順序（必須）

1. **`docs/sessions/LATEST.md`** — 現在の状態、何が完了していて何が未完了か
2. **`AGENTS.md`** — エージェント設計（ディスカッション型アーキテクチャ）
3. **`docs/requirements.md`** — 要件定義
4. **`docs/sessions/20260407_codex_consultation.md`** — Codexとの設計合意（最新の設計判断）
5. **`docs/sessions/20260407_monetization_research.md`** — マネタイズ戦略
6. **`docs/sessions/20260407_image_vision_design.md`** — 画像Vision設計

### 起動後の自動アクション

1. `git pull` で最新コードを取得
2. LATEST.md の状態を確認
3. デグレチェック: `python -c "import main"` でインポートエラーがないか確認
4. LATEST.md の「Next Resume Actions」を順に実行
5. 問題があれば修正、なければ次のタスクへ

---

## 🔴 ツールの理念（絶対に守ること）

**タイトルは攻めていい。グレーギリギリでも合法なら構わない。**
**ただし大々的に謳った以上、中身は絶対に濃くなければならない。**
**タイトル負け = 読者への裏切り = 絶対禁止。**

これは全エージェント、全プロンプト、全スコアリングに浸透済みの最上位ルール。

---

## プロジェクト概要

Zenn（技術記事）とnote（一般向け）に高品質な記事を自動生成・投稿するシステム。
5つの専門エージェント（Researcher/Strategist/Writer/Critic/Coordinator）がディスカッションして品質を担保する。

### ターゲットコンテンツ

**Zenn（有料記事・技術系プレミアム）:**
- AIツール実践ガイド（Claude Code、Cursor、v0等）
- まだ世に広まっていない最新論文の解説
- AI × マネタイズの実務手順
- エージェント時代の新スキルセット

**note（バズるコンテンツ）:**
- 韓国トレンド・美容・K-POP
- 隠れた名店グルメ（チェーン店禁止、個人店のみ）
- コーヒー・バリスタ文化
- 美意識高め層向けの自分磨き
- AI副業・マネタイズ系

### 絶対ルール

- チェーン店は紹介しない（個人店・隠れた名店のみ）
- 架空の店名・住所・メニュー名は書かない（元ソースにある情報のみ）
- 有名人言及は公式ソース（Tier1-2）がある場合のみ
- タイトルで煽った内容は本文で必ず回収する

---

## デグレチェック手順

コード変更後、必ず以下を確認:

```bash
# 1. インポートチェック（全モジュールが読み込めるか）
python -c "import main"
python -c "from generators.objective_scorer import ObjectiveScorer"
python -c "from generators.subjective_evaluator import SubjectiveEvaluator"
python -c "from generators.score_aggregator import ScoreAggregator"
python -c "from utils.article_store import ArticleStore"
python -c "from utils.sheets_manager import SheetsManager"
python -c "from publishers.gmail_notifier import GmailNotifier"
python -c "from generators.cover_generator import CoverGenerator"
python -c "from generators.hashtag_generator import HashtagGenerator"
python -c "from collectors.rss_collector import RssCollector"

# 2. 収集テスト（API不要、RSS/arXivのみ）
python main.py --collect-only

# 3. ドライラン（Ollama必要、Sheets/投稿なし）
python main.py --dry-run

# 4. Sheets接続テスト
python main.py --setup-sheets
```

---

## アーキテクチャ

### パイプライン

```
--generate:
  収集(arXiv + RSS日本語 + RSS韓国 + Reddit)
    → トレンドスコアでランク付け
    → 構成パターン自動選択（listicle, trend_report, howto, tutorial等）
    → LLM記事生成（プロンプトに構成パターン注入）
    → カバー画像自動生成（テーマ別グラデーション）
    → 客観スコアリング（ObjectiveScorer: 引用数、Tier比率、視覚要素、チェーン店検出）
    → 主観スコアリング（SubjectiveEvaluator: 独自性、正確性、可読性、引き込み）
    → 集約判定（ScoreAggregator: A/B/C。Cは自動却下）
    → ArticleStoreに保存（data/articles/*.json）
    → Sheetsに「⏳承認待ち」で登録
    → Gmail通知

--publish:
  Sheetsから「✅承認」取得
    → ArticleStoreからコンテンツ読み込み
    → ハッシュタグ自動生成
    → Zenn: Git push（published: true）
    → note: Selenium投稿（価格はA/B/Cグレードから自動算出）
    → Slack + Gmail通知
```

### スコアリング（2層）

```
客観（プログラム計測 — 足切り）:
  エビデンスレベル: Tier1-2率 → A(80%+) / B(60%+) / C(<60%)
  引用数: A(5+) / B(2-4) / C(0-1)
  引用形式: URL+日付の充足率
  視覚要素: A(5+) / B(2-4) / C(0-1)
  禁止フレーズ: 0件=Pass, 1+=Fail
  チェーン店: 0件=Pass, 1+=Fail

  客観Cが1つでもあれば → 総合C → 自動却下

主観（LLM評価 — 根拠必須）:
  独自性 / 正確性 / 可読性 / 引き込み → 各A/B/C

総合: min(客観最低値, 主観平均)
```

### note有料化

```
A + A証拠 → ¥1,980
A + B証拠 → ¥980
B + A証拠 → ¥500
B + B証拠 → ¥300
その他    → 無料
```

---

## ファイル構成（主要）

```
main.py                          # メインパイプライン
bot/slack_bot.py                 # Slack Bot（遠隔操作）
collectors/
  arxiv_collector.py             # arXiv論文（7カテゴリ）
  reddit_collector.py            # Reddit
  rss_collector.py               # 日本語+韓国+グルメ+コーヒー RSS
  trend_detector.py              # トレンドスコア計算
generators/
  objective_scorer.py            # 客観スコア（足切り）
  subjective_evaluator.py        # 主観スコア（根拠必須）
  score_aggregator.py            # A/B/C判定
  cover_generator.py             # カバー画像（テーマ別）
  hashtag_generator.py           # ハッシュタグ自動生成
  image_sourcer.py               # 著作権安全画像
  rich_formatter.py              # リッチテキスト強化
  evidence_manager.py            # エビデンス検証
  note_content_converter.py      # Mermaid→PNG（note用）
  local_llm.py                   # Ollama連携
publishers/
  zenn_publisher.py              # Zenn投稿（Git）
  note_publisher.py              # note投稿（Selenium）
  gmail_notifier.py              # Gmail通知
  slack_notifier.py              # Slack Webhook通知
utils/
  article_store.py               # 記事コンテンツ保存
  sheets_manager.py              # Google Sheets 14列ダッシュボード
  token_manager.py               # トークン予算管理
  feedback_recorder.py           # フィードバック記録（v1.1分析用）
config/
  prompts.yaml                   # プロンプト（理念・構成パターン含む）
  settings.yaml.example          # システム設定
```

---

## Slack Bot コマンド（遠隔操作）

```
#ai-publisher チャンネルで:
  generate  — 収集→生成→スコアリング→Sheets登録
  publish   — 承認済み記事を投稿
  collect   — 収集+ランクのみ
  dryrun    — 生成+スコアまで
  stop      — 実行中タスク停止
  status    — 状態確認
  sheets    — Sheetsリンク表示
  help      — コマンド一覧
```

---

## スキル定義

`.claude/skills/` と `.codex/skills/` に同一内容で配置（更新時は両方同期）:

**パイプラインスキル:** core, collection, generation, quality-gate, publishing, self-improvement
**エージェントスキル:** researcher, strategist, writer, critic, coordinator

---

## 開発時の注意

- `.claude/skills/` と `.codex/skills/` は同一内容。更新時は両方同期
- 品質スコアは A/B/C グレード制（旧数値スコアは廃止）
- Mermaidオンラインレンダリングは無効化（セキュリティ: 記事内容の外部送信防止）
- 画像はCC0/Unsplash/Pexels/AI生成のみ使用可
- チェーン店ブラックリストは `config/settings.yaml` の `evidence.gourmet_rules.chain_blacklist`
- 構成パターンは `config/prompts.yaml` の `article_structures` + `structure_selection`

---

## 🎯 Compound Workflow Playbook (他セッションから同じ結果を出すための定型)

ユーザーの自然言語指示 → 実行手順の正規化マッピング。新しいセッションから resume/compound 指示が来たとき、この表に沿って自走する。

### 1. 「ジェネレートして全部承認してパブリッシュ」

```bash
# Phase 1: 収集→生成→スコアリング→Sheets登録
PYTHONIOENCODING=utf-8 py main.py --generate

# Phase 2: 承認待ち全行を ✅承認 に
PYTHONIOENCODING=utf-8 py scripts/_bulk_approve_sheet.py

# Phase 3: 承認済みを投稿 (note は全部 paid、zenn は cap で scrap fallback)
PYTHONIOENCODING=utf-8 py scripts/_publish_free_first.py --free-first 0
```

### 2. 「無料 N 本 + 有料 M 本」 (note のみ)

`_publish_free_first.py --free-first N` で **note の最初 N 本のみ price=0**、残りは `determine_price()` で paid。N は note 承認行数を超えると残り無視。

```bash
PYTHONIOENCODING=utf-8 py scripts/_publish_free_first.py --free-first 2
```

note 4 本承認なら 2 free + 2 paid になる。zenn は cap で scrap に落ちる (`_zenn_cap_exhausted` の batch flag)。

### 3. 「スクラップ記事投稿」

承認 publish ではなく、data/scraps/ にあるが未公開のドラフトを ZennScrapPublisher で post する。

```bash
# 未投稿の最新スクラップを N 本投稿 (デフォルト 20)
PYTHONIOENCODING=utf-8 py scripts/_publish_pending_scraps.py --limit 10

# 期間制限したい場合
PYTHONIOENCODING=utf-8 py scripts/_publish_pending_scraps.py --limit 10 --max-age-hours 168
```

判定: `data/articles/{aid}.json` の `published_url` が空 (or 未存在) なら未投稿。タイトル抽出は H1 → 本文先頭 plain text → ファイル名の fallback 順。

### 4. 「画像を ChatGPT で生成し直して」

直近投稿した 4 本に対しては:

```bash
# Brave 完全停止 (CDP モード未設定なら必須)
taskkill /F /IM brave.exe

# 4 本固定の regen (cover + inline) — TARGETS は適宜編集
PYTHONIOENCODING=utf-8 py scripts/_regen_today_note_with_chatgpt.py
```

任意の最近記事には `scripts/fix_recent_note_images.py` (Unsplash) または `scripts/regen_eyecatch_with_chatgpt.py` (cover のみ)。

**known bug (2026-05-13 実証):** edit_article が「更新ボタンが見つかりません」で FAIL を返しても、note 側では大半保存されている (og:image 更新済)。FAIL ログ無視して `curl` / og:image 確認で真偽判定。

### 5. Brave CDP モード (Brave 開きっぱで ChatGPT 画像生成)

```bash
scripts/launch_brave_cdp.bat
```

`.env` の `CHATGPT_CDP_PORT=9222` が読まれて `connect_over_cdp` 経由 attach。Brave を常駐運用したい場合の既定モード。`launch_persistent_context` (Brave kill が必要) は CDP 接続失敗時の自動フォールバック。

---

## 📜 Scripts カタログ (新しめのもの)

`_` (underscore) prefix = 一回限り / 状況限定の one-shot。継続運用するなら明示 prefix を外す。

| script | 用途 |
|--------|------|
| `_bulk_approve_sheet.py` | Sheets の ⏳承認待ち を batch_update で一括 ✅承認。guard なし版 (バリデーション必要なら `bulk_approve.py`) |
| `_publish_free_first.py` | `publish_approved` を呼ぶ。`--free-first N` で note の最初 N 本だけ ¥0 に override |
| `_publish_pending_scraps.py` | `data/scraps/*.md` の未投稿ドラフトを ZennScrapPublisher で投稿。タイトル抽出 + deny check 内蔵 |
| `_regen_today_note_with_chatgpt.py` | 直近 publish の 4 本に対し ChatGPT 画像で cover+inline を再生成 → `edit_article` で差し替え |
| `launch_brave_cdp.bat` | Brave を `--remote-debugging-port=9222` で起動 (CDP attach 用) |

定常運用スクリプト (継続):
- `scripts/bulk_approve.py` — グレード C / SNS hallucination guard 付きの bulk approve
- `scripts/fix_recent_note_images.py` — note 既存記事のインライン Unsplash 差し替え
- `scripts/regen_eyecatch_with_chatgpt.py` — note 既存記事の eyecatch だけ ChatGPT で差し替え
- `scripts/publish_scraps_as_articles.py` — scrap を full article として publish (cap 中は使えない)

---

## 🚧 既知の運用上の罠 (publish 関連)

### Zenn article cap (2026-04-15 以降)

- 12 本程度を超えると git push しても **silently 404** になる
- `publish_approved` は 1 本目で 404 検出 → `_zenn_cap_exhausted=True` flag → 同 batch の残りは scrap fallback
- 次回 publish 前にダッシュボードで cap 状況確認するまで scrap-only モード推奨

### note `_set_price` の price input 不可視 (2026-05-13)

- ¥300 default で進行する false-path がある (UI セレクタ漂流)
- determine_price 表で B+B = ¥300 なので一致するケースが多いが、A+A の ¥1980 articles でも ¥300 で publish されると損失
- 検証: publish 後に note ダッシュボードで価格確認、間違っていれば edit で修正

### note membership-add ボタン消失

- 「メンバー特典記事を追加する」ボタンが post-publish flow で見つからない (タイミング or UI 変更)
- best-effort なので publish 自体は成功、ただし membership には未追加 → ダッシュボードから手動追加が必要

## Monitor / バックグラウンドタスクの後始末

Claude Code の `Monitor` ツール (`tail -F ... | grep ...`) を使った後は、
`TaskStop` だけだと Windows 上で子プロセス (`tail.exe` / `grep.exe`) が
孤児化して残ることがある (シグナル伝播の問題)。

ターン終了前に必ず以下を実行してクリーンアップ:

```powershell
Get-Process tail,grep -ErrorAction SilentlyContinue | Stop-Process -Force
```

何もぶら下がっていなければ no-op。害は無いが、何セッションも続けると
プロセス表が tail.exe で埋まる。
