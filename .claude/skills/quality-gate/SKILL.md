---
name: quality-gate
description: Use after article generation to evaluate quality. Scores articles on 5 dimensions and determines pass/fail for publishing.
---

# Quality Gate Skill

## Purpose

生成記事の品質を5軸で評価し、投稿可否を判定する。
基準未達の記事は再生成を指示するか除外する。

---

## Workflow

1. Receive generated article from `generation` skill.
2. Send article to LLM for evaluation via `QualityEvaluator`.
3. Parse JSON scores from LLM response.
4. Check against threshold:
   - Zenn: min 45/50
   - note: min 40/50
5. If PASS → forward to `publishing` skill.
6. If FAIL → attempt regeneration (max 2 retries).
7. If still FAIL after retries → log and skip.

---

## Module

| Module | Class | Role |
|--------|-------|------|
| `generators/quality_evaluator.py` | `QualityEvaluator` | 品質スコアリング |

---

## Evaluation Dimensions (各 0-10)

| Dimension | Label | Weight Focus |
|-----------|-------|-------------|
| `originality` | 独自性 | 翻訳以上の価値 |
| `accuracy` | 技術的正確性 | コード・説明の正しさ |
| `readability` | 可読性・構成 | 見出し・図表・リスト |
| `citation` | 引用の適切性 | 出典明記・参考文献 |
| `practicality` | 実用性 | 読者が実践可能 |

---

## Pass/Fail Criteria

```
total = originality + accuracy + readability + citation + practicality
pass = total >= min_quality_score (from settings.yaml)
```

| Platform | Min Score | Max Retries |
|----------|-----------|-------------|
| Zenn | 45/50 | 2 |
| note | 40/50 | 2 |

---

## Evidence Checks (Pre-evaluation)

- `EvidenceManager.validate_citations()` → 引用形式チェック
- `EvidenceManager.check_forbidden_phrases()` → 禁止表現チェック
  - 「月○万円稼いだ」「誰でも稼げる」「簡単に収益」等

---

## Rules

- 品質スコアはJSON形式でパースする（コードブロック内も対応）
- パース失敗時はデフォルト0点（= 不合格）
- 再生成時はフィードバック内容をプロンプトに追加する
- 全dimension 5点以上なら引用不備があっても条件付き合格
- 連続不合格パターンは `docs/knowledge/` に記録する

---

## Output

Evaluation result containing:
- `scores` (per-dimension dict)
- `total` (int, 0-50)
- `pass` (bool)
- `feedback` (str)
- `should_regenerate` (bool)

---

## STOP CONDITION

- 全記事の評価が完了したら停止。
- 再生成上限に達した記事はスキップして次へ。
