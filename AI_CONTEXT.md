# AI Context

## Repository Purpose

AI記事自動生成・投稿システム。外部ソースから記事を収集し、LLMで高品質な記事を生成、Zenn/noteに自動投稿する。

## Architecture

パイプライン型アーキテクチャ:

```
Collectors → TrendDetector → Generators → QualityEvaluator → Publishers → Notifier
```

## Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `collectors/` | 外部ソース（arXiv, Reddit）からの記事収集 |
| `generators/` | LLM（Claude.ai/Ollama）による記事生成 |
| `publishers/` | プラットフォーム（Zenn/note）への投稿 |
| `utils/` | 横断的関心事（ログ、トークン管理、Sheets連携） |
| `config/` | 設定・プロンプトテンプレート |
| `.claude/skills/` | エージェントスキル定義（Claude Code用、プライマリ） |
| `.codex/skills/` | エージェントスキル定義（Codex CLI互換エイリアス） |
| `docs/` | 実行ログ・知見・アーキテクチャ決定 |

## Key Design Decisions

- Claude.aiはSelenium経由（API不使用、ランニングコスト0円のため）
- Ollama/CodeLlamaをフォールバックLLMとして使用
- Zenn投稿はGit経由（公式サポート方式）
- note投稿はSelenium経由（公式API未公開のため）
- 品質評価は5軸50点満点のスコアリング
- トークン消費は週次予算管理

## Configuration

- `config/settings.yaml` — 収集・生成・投稿・価格設定
- `config/prompts.yaml` — LLMプロンプトテンプレート
- `.env` — API キー・パス等の秘密情報
