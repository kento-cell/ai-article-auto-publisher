---
name: generation
description: Use when generating articles from collected sources using Claude.ai or local LLM. Handles prompt formatting, diagram generation, and evidence management.
---

# Generation Skill

## Purpose

収集された記事をもとに、Zenn/note向けの高品質な記事を生成する。

---

## Workflow

1. Load `core` skill for context.
2. Check token budget via `TokenManager`.
   - Budget OK → Claude.ai (Selenium)
   - Budget exceeded → Ollama/CodeLlama (local fallback)
3. Load prompt template from `config/prompts.yaml`.
4. For each ranked article (up to `articles_per_week`):
   a. Format prompt with article data.
   b. Send to LLM and receive generated content.
   c. Process Mermaid diagrams → SVG via `DiagramGenerator`.
   d. Validate evidence/citations via `EvidenceManager`.
   e. Check forbidden phrases.
   f. Record token usage.
5. Pass generated articles to `quality-gate` skill.

---

## Modules

| Module | Class | Role |
|--------|-------|------|
| `generators/claude_automator.py` | `ClaudeAutomator` | Claude.ai Selenium操作 |
| `generators/local_llm.py` | `LocalLLM` | Ollama API連携 |
| `generators/diagram_generator.py` | `DiagramGenerator` | Mermaid→SVG変換 |
| `generators/evidence_manager.py` | `EvidenceManager` | 引用検証・禁止フレーズ |

---

## LLM Selection Logic

```
if TokenManager.is_within_budget():
    try ClaudeAutomator
    except → fallback to LocalLLM
else:
    use LocalLLM
```

---

## Rules

- トークン消費は必ず記録する
- 禁止フレーズ検出時はその記事をスキップ
- 引用不備は `add_access_date()` で自動補完を試みる
- Mermaid図がレンダリング失敗してもテキスト版を残す
- Claude.ai セッション切れ時は即座にローカルLLMへ切り替え

---

## Prompt Templates

- `zenn_article_prompt` — 技術記事向け（引用厳格、コード必須）
- `note_article_prompt` — 一般向け（平易、図解多め）

---

## Output

Generated articles, each containing:
- `title`, `content` (Markdown), `source` (original article data)
- Token usage count

---

## STOP CONDITION

- `articles_per_week` 分の記事を生成したら停止。
- トークン完全枯渇時は即時停止。
