# AI記事自動生成・投稿システム

完全自動のAI記事生成・投稿システム。Zenn（技術記事）とnote（一般向け記事）に対応。

## 特徴

- **自動収集**: arXiv論文、Reddit等からトレンド記事を自動収集
- **AI記事生成**: Claude.ai（Selenium経由）またはローカルLLM（Ollama/CodeLlama）で記事生成
- **品質管理**: 5軸評価（独自性・正確性・可読性・引用・実用性）で自動スコアリング
- **自動投稿**: Zenn（Git経由）・note（Selenium経由）に自動投稿
- **有料化対応**: noteの品質スコアベース自動価格設定
- **エビデンス検証**: 引用チェック・禁止フレーズ検出
- **通知**: Slack Webhookで投稿結果を通知
- **トークン管理**: 週次トークン消費量を追跡・予算管理
- **ランニングコスト0円**: ローカルLLM + 無料枠で運用可能

## アーキテクチャ

```
収集(Collectors) → トレンド分析 → 記事生成(Generators) → 品質評価 → 投稿(Publishers) → 通知
```

```
ai-article-auto-publisher/
├── main.py                 # メインパイプライン
├── collectors/             # 記事収集モジュール
│   ├── arxiv_collector.py  # arXiv論文収集
│   ├── reddit_collector.py # Reddit収集
│   ├── trend_detector.py   # トレンドスコア計算
│   └── base_collector.py   # 基底クラス
├── generators/             # 記事生成モジュール
│   ├── claude_automator.py # Claude.ai Selenium自動操作
│   ├── local_llm.py        # Ollama/CodeLlama連携
│   ├── diagram_generator.py# Mermaid図表生成
│   ├── evidence_manager.py # エビデンス検証
│   └── quality_evaluator.py# 品質評価
├── publishers/             # 投稿モジュール
│   ├── zenn_publisher.py   # Zenn投稿（Git経由）
│   ├── note_publisher.py   # note投稿（Selenium経由）
│   └── slack_notifier.py   # Slack通知
├── utils/                  # ユーティリティ
│   ├── sheets_manager.py   # Google Sheets連携
│   ├── token_manager.py    # トークン管理
│   └── logger.py           # ログ設定
├── config/                 # 設定ファイル
│   ├── prompts.yaml        # プロンプトテンプレート
│   └── settings.yaml       # システム設定
└── docs/                   # ドキュメント
```

## セットアップ

### 前提条件

- Python 3.10+
- Google Chrome
- Git

### 1. クローン & セットアップ

```bash
git clone https://github.com/kento-cell/ai-article-auto-publisher.git
cd ai-article-auto-publisher
chmod +x setup.sh
./setup.sh
```

### 2. 環境変数設定

`.env` を編集:

```env
GOOGLE_SHEETS_CREDENTIALS_PATH=./config/credentials.json
GOOGLE_SHEET_ID=your_sheet_id
NOTE_API_TOKEN=your_note_token
ZENN_REPO_PATH=/path/to/zenn-repo
SLACK_WEBHOOK_URL=your_slack_webhook
CHROME_PROFILE_PATH=/path/to/chrome/profile
OLLAMA_API_URL=http://localhost:11434
```

### 3. Google Sheets API設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト作成
2. Google Sheets API を有効化
3. サービスアカウント作成 → JSONキーをダウンロード
4. `config/credentials.json` に配置
5. 対象スプレッドシートにサービスアカウントのメールを共有

### 4. Zenn連携

1. [Zenn CLIでのリポジトリ連携](https://zenn.dev/zenn/articles/connect-to-github)に従いGitHubリポジトリを作成
2. `.env` の `ZENN_REPO_PATH` にローカルクローンパスを設定

### 5. Ollama（オプション）

```bash
# Ollamaインストール後
ollama pull codellama
```

## 使い方

### 記事収集のみ

```bash
python main.py --collect-only
```

### ドライラン（投稿なし）

```bash
python main.py --dry-run
```

### フル実行

```bash
python main.py
```

### 定期実行（cron）

```bash
# 毎日22時に実行
0 22 * * * cd /path/to/ai-article-auto-publisher && venv/bin/python main.py
```

## 設定カスタマイズ

### config/settings.yaml

| 項目 | 説明 | デフォルト |
|------|------|-----------|
| `collection.zenn.max_articles` | Zenn向け最大収集数 | 10 |
| `collection.note.max_articles` | note向け最大収集数 | 20 |
| `generation.zenn.articles_per_week` | Zenn週間生成数 | 3 |
| `generation.note.articles_per_week` | note週間生成数 | 2 |
| `generation.*.min_quality_score` | 最低品質スコア（/50） | 45 (Zenn), 40 (note) |
| `token_management.weekly_limit` | 週間トークン上限 | 2,000,000 |
| `pricing.thresholds.*` | note有料化閾値 | 700/1000/1500/2000 |

### 品質評価基準

| 項目 | 満点 | 内容 |
|------|------|------|
| オリジナリティ | 10 | 独自の視点・解説 |
| 技術的正確性 | 10 | 技術説明の正しさ |
| 視認性・構成 | 10 | 見出し・コード・図表 |
| 引用の適切性 | 10 | 出典明記・参考文献 |
| 実用性 | 10 | 実践的な内容 |

## トラブルシューティング

### Selenium関連

**Chrome起動エラー**
```
selenium.common.exceptions.WebDriverException: Message: unknown error: Chrome failed to start
```
→ `CHROME_PROFILE_PATH` が正しいか確認。Chrome本体を閉じてから再実行。

**要素が見つからない**
→ Claude.ai/noteのUI変更の可能性。`claude_automator.py`/`note_publisher.py` のセレクタを更新。

### Ollama関連

**接続エラー**
```
ConnectionError: Failed to connect to Ollama
```
→ `ollama serve` が起動中か確認。`OLLAMA_API_URL` を確認。

### Google Sheets関連

**認証エラー**
→ `config/credentials.json` の配置とスプレッドシートの共有設定を確認。

### トークン超過

→ `config/settings.yaml` の `token_management.weekly_limit` を調整。
→ `data/token_usage.json` を確認して手動リセット可能。

## ライセンス

MIT License
