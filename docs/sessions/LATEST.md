# Latest Session

## Current Topic

ai-article-auto-publisher — v1.0 コード実装完了、自宅PCで自走テスト開始

## Current Status

- **Phase**: v1.0 コード完了 → 自宅PCでデグレ確認+E2Eテスト
- **Pipeline**: Zenn投稿確認済み（デスクトップで動作確認OK）

## Next Resume Actions（自走で実行すること）

### 1. デグレチェック（最優先）

```bash
git pull
python -c "import main"
python -c "from generators.objective_scorer import ObjectiveScorer"
python -c "from generators.subjective_evaluator import SubjectiveEvaluator"
python -c "from generators.score_aggregator import ScoreAggregator"
python -c "from generators.cover_generator import CoverGenerator"
python -c "from generators.hashtag_generator import HashtagGenerator"
python -c "from collectors.rss_collector import RssCollector"
python -c "from utils.article_store import ArticleStore"
```

インポートエラーがあれば修正。

### 2. 収集テスト

```bash
python main.py --collect-only
```

arXiv + Reddit + 日本語RSS + 韓国RSS が全て動くか確認。
エラーのあるRSSフィードは除外するかURLを修正。

### 3. ドライラン

```bash
python main.py --dry-run
```

記事生成 + 構成パターン選択 + 客観/主観スコアリング + カバー画像生成が通るか確認。
Ollama (Gemma3) が起動していること。

### 4. 生成→Sheets登録テスト

```bash
python main.py --generate
```

Sheetsに記事が「⏳承認待ち」で登録されるか確認。
Gmail通知が届くか確認。

### 5. Slack Bot 動作確認

```bash
python bot/slack_bot.py
```

Slackの #ai-publisher で `status` `help` `collect` が動くか確認。

### 6. 問題があれば修正して再テスト

エラーが出たら:
1. エラーメッセージを読んで原因特定
2. 修正
3. デグレチェックを再実行
4. 修正をコミット・プッシュ

## 今日の会社PCでの変更（未テスト）

以下は会社PCでコード作成したが、自宅PCでの実行テストが未了:

- **構成パターンローテーション接続** — main.pyが記事内容に応じて8パターンから自動選択
- **架空店名対策（ハルシネーション防止）** — プロンプトで「元ソースにある情報のみ使用」を強制
- **コンテンツ理念の反映** — 攻めタイトル + 濃密な中身（タイトル負け禁止）
- **プレミアムコンテンツソース追加** — OpenAI Blog, Anthropic, HuggingFace, HN AI, There's An AI For That
- **韓国+グルメ+コーヒーソースのRSS** — allkpop, Soompi, @cosme, 食べログ, Retty, Standart Japan等
- **有名人匂わせタイトルのルール** — 伏字OK、実名はTier1-2ソース必須
- **Criticのタイトル-本文一致チェック強化**
- **arXivカテゴリ拡張** — cs.MA(マルチエージェント), cs.SE(コード生成), cs.CR(セキュリティ)追加

## Key Documents

| ファイル | 内容 |
|---------|------|
| CLAUDE.md | セットアップ手順、デグレチェック手順、日常運用 |
| AGENTS.md | ディスカッション型アーキテクチャ、スコアリング基準 |
| docs/requirements.md | 要件定義 v1.1 |
| docs/sessions/20260407_codex_consultation.md | Codex設計合意（5件の相談+回答） |
| docs/sessions/20260407_monetization_research.md | マネタイズ戦略リサーチ |
| docs/sessions/20260407_image_vision_design.md | 画像Vision設計（v1.1） |
| docs/sessions/20260407_codex_review_response.md | バグ修正レポート + 反省点 |
| config/prompts.yaml | プロンプト（理念、構成パターン、バズるタイトル型） |
| config/settings.yaml.example | チェーン店ブラックリスト、構成ローテーション設定等 |

## Updated At

2026-04-08 JST
