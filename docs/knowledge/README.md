# Knowledge Base

AI記事自動生成システムの品質向上のためのナレッジ集積所。
各カテゴリ別に学習内容・ベストプラクティス・事例を蓄積する。

## トップレベルファイル

- **`hallucination_registry.md`** — 過去のハルシネーション事故と対策の正典 (canonical)。
  新しい事故が起きたら必ずここに追記し、deny pattern を 3 箇所 (settings.yaml /
  settings.yaml.example / main.py `_PUBLISH_DENY_PATTERNS`) に同期する。
- `quality_anti_patterns.md` — 低エンゲージメントから自動抽出されたアンチパターン。
- `quality_recurring_failures.md` — 繰り返し観測される構造的不合格パターン。
- `quality_successes.md` — 高エンゲージメント記事の共通点。
- `quality_codex_grounded_scoring.md` — Codex 連携時のスコア基準。

## カテゴリ

### `note-trends/`
- noteで伸びる記事の傾向分析
- 有料記事の売れ筋パターン
- タイトル・構成・導入のベストプラクティス
- カテゴリ別（ビジネス、ライフスタイル、テック等）

### `monetization/`
- noteマネタイズ手法
- 有料記事の価格設定戦略
- サブスクリプション vs 単品販売
- 伸びるクリエイターの共通点

### `claude-usage/`
- Claude活用のコツ
- プロンプトエンジニアリング
- API vs ローカルLLMの使い分け
- トークン節約テクニック

### `image-generation/`
- 画像生成ツール比較（DALL-E, SD, Pollinations等）
- 記事カバー画像のデザインパターン
- noteでの画像添付方法
- 著作権安全な画像ソース

## ファイル命名規則
- `YYYY-MM-DD_topic.md` — 日付付き研究ノート
- `pattern_*.md` — 再利用可能なパターン
- `case_study_*.md` — 具体事例

## 使い方

1. 新しい知見を得たら該当カテゴリにMarkdownで記録
2. プロンプトに活用するならcategory summaryを更新
3. 定期的に見直して陳腐化したものは削除
