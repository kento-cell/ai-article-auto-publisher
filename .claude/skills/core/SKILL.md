---
name: core
description: Use when starting a new task or pipeline run. Establish minimal context using latest session and AGENTS.md.
---

# Core Skill

## Purpose

パイプライン実行時の最小限コンテキスト復元と基本行動ルールを提供する。

---

## Entry Workflow (STRICT ORDER)

1. Read `docs/sessions/LATEST.md`
   - 前回の実行結果、エラー状態、トークン残量を把握

2. Read `AGENTS.md`
   - パイプラインルールと制約を確認

3. Read `config/settings.yaml`
   - 現在の収集・生成・投稿設定を確認

4. Load additional context ONLY when necessary:
   - `docs/knowledge/*` — 過去の品質パターン
   - `docs/context/*` — 背景情報

---

## Rules

- DO NOT preload all docs files
- ALWAYS check token budget before generation phase
- ALWAYS prioritize latest session state over static documentation
- Context loading must be demand-driven
- Pipeline errors should be logged, not silently swallowed

---

## Scope

- Always active for any repository interaction
- Provides baseline context for all other skills

---

## Non-Goals

- No article generation logic
- No quality evaluation logic
- No publishing logic

---

## STOP CONDITION

- Stop loading context once sufficient understanding is achieved.
