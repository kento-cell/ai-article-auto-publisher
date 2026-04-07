# Claude Code — AI記事自動生成システム

## プロジェクト概要

Zenn（技術記事）とnote（一般向け）に高品質な記事を自動生成・投稿するシステム。
5つの専門エージェント（Researcher/Strategist/Writer/Critic/Coordinator）が議論して品質を担保する。

## 最初に読むファイル

1. `AGENTS.md` — エージェント運用ガイド（ディスカッション型アーキテクチャ）
2. `docs/sessions/LATEST.md` — 現在の状態
3. `docs/requirements.md` — 要件定義
4. `AI_CONTEXT.md` — リポジトリ構造

## セットアップ手順（初回）

ユーザーが「セットアップして」と言ったら、以下を順に実行:

### 1. Python仮想環境

```bash
python -m venv venv
venv\Scripts\activate    # Windows
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. 設定ファイル

```bash
# .env がなければコピー
copy .env.example .env
# settings.yaml がなければコピー
copy config\settings.yaml.example config\settings.yaml
```

→ ユーザーに `.env` の各値を確認してもらう:
- `GOOGLE_SHEET_ID`: Google SheetsのスプレッドシートID
- `GOOGLE_SHEETS_CREDENTIALS_PATH`: サービスアカウントJSONのパス
- `GMAIL_SENDER`: 送信元Gmailアドレス
- `GMAIL_RECIPIENT`: 通知先メールアドレス
- `ZENN_REPO_PATH`: Zennリポジトリのローカルパス
- `CHROME_PROFILE_PATH`: Chromeプロファイルのパス
- `OLLAMA_API_URL`: Ollama APIのURL（デフォルト: http://localhost:11434）
- `UNSPLASH_ACCESS_KEY` / `PEXELS_API_KEY`: 画像API（オプション）

### 3. Ollama（ローカルLLM）

```bash
# Ollamaがインストール済みか確認
ollama --version
# CodeLlamaを取得
ollama pull codellama
# Vision対応（v1.1以降）
# ollama pull qwen2.5vl
```

### 4. Google Sheets初期設定

```bash
python main.py --setup-sheets
```

→ ドロップダウン、条件付き書式、列幅、ヘッダー固定が自動設定される

### 5. 動作確認

```bash
python main.py --collect-only
```

→ arXiv/Redditから記事を収集してトレンドスコア表示

## 日常運用コマンド

| コマンド | 動作 |
|---------|------|
| `python main.py --generate` | 収集→生成→スコアリング→Sheets登録→Gmail通知 |
| `python main.py --publish` | Sheetsで「✅承認」の記事を投稿 |
| `python main.py --collect-only` | 収集+ランク付けのみ |
| `python main.py --dry-run` | 生成+スコアリングまで（Sheets/投稿なし） |
| `python main.py --setup-sheets` | Sheetsフォーマット初期設定 |

## 承認フロー

```
--generate 実行
  → 記事生成 + 2層スコアリング（客観+主観）
  → 総合C → 自動却下（ユーザーに見せない）
  → 総合A/B → Sheetsに「⏳承認待ち」で登録
  → Gmail通知が届く

ユーザー: Sheetsを開いてスコア確認
  → ステータスのドロップダウンで「✅承認」を選択

--publish 実行
  → 「✅承認」の記事だけ Zenn/note に投稿
  → Gmail + Slack で投稿完了通知
```

## スコアリング基準

### 客観スコア（プログラム計測 — 足切り）

| 指標 | A | B | C（足切り） |
|------|---|---|-----------|
| エビデンスレベル | Tier1-2率 80%+ | 60-79% | 60%未満 |
| 引用数 | 5個以上 | 3-4個 | 0-2個 |
| 引用形式 | 全数URL+日付 | 80%+ | 80%未満 |
| 視覚要素 | 5個以上 | 3-4個 | 0-2個 |
| 禁止フレーズ | 0件 | — | 1件以上=Fail |

**客観Cが1つでもあれば総合C → 自動却下**

### 主観スコア（LLM評価 — 根拠必須）

| 指標 | 評価者 |
|------|--------|
| 独自性 | Strategist差別化根拠 + Critic評価 |
| 正確性 | Researcher検証結果 + Critic指摘 |
| 可読性 | Critic構成評価 |
| 引き込み | Critic「So what?」テスト |

## スキル定義

`.claude/skills/` に11スキル:
- core, collection, generation, quality-gate, publishing, self-improvement
- researcher, strategist, writer, critic, coordinator

## 開発時の注意

- `.claude/skills/` と `.codex/skills/` は同一内容。更新時は両方同期
- 品質スコアは A/B/C グレード制（旧数値スコアは廃止）
- Mermaidオンラインレンダリングは無効化（セキュリティ）
- 画像はCC0/Unsplash/Pexels/AI生成のみ使用可
