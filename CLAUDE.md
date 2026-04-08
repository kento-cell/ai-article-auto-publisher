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
