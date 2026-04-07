---
name: publishing
description: Use after quality gate approval to publish articles to Zenn and note, and send Slack notifications.
---

# Publishing Skill

## Purpose

品質合格した記事をZenn・noteに投稿し、結果をSlackに通知する。

---

## Workflow

1. Receive quality-approved articles.
2. For Zenn articles:
   a. `ZennPublisher.create_article()` — Markdown + frontmatter作成
   b. `ZennPublisher.publish()` — git add/commit/push
3. For note articles:
   a. `NotePublisher.determine_price()` — 品質スコアベース価格設定
   b. `NotePublisher.publish_article()` — Selenium経由で投稿
4. Record results to Google Sheets via `SheetsManager`.
5. Send Slack notifications:
   - 投稿成功: `notify_published()`
   - エラー: `notify_error()`
   - 日次サマリー: `notify_daily_summary()`

---

## Modules

| Module | Class | Role |
|--------|-------|------|
| `publishers/zenn_publisher.py` | `ZennPublisher` | Zenn Git投稿 |
| `publishers/note_publisher.py` | `NotePublisher` | note Selenium投稿 |
| `publishers/slack_notifier.py` | `SlackNotifier` | Slack通知 |
| `utils/sheets_manager.py` | `SheetsManager` | Google Sheets記録 |

---

## Zenn Publishing Flow

```
create_article(title, content, topics)
  → articles/{slug}.md (with YAML frontmatter)
  → publish(slug)
    → git add → git commit → git push
```

Frontmatter format:
```yaml
---
title: "記事タイトル"
emoji: "🤖"
type: "tech"
topics: ["AI", "機械学習"]
published: true
---
```

---

## note Pricing Tiers

| Quality Score | Word Count | Price |
|--------------|------------|-------|
| < 700 | any | ¥0 (free) |
| 700-999 | any | ¥300 |
| 1000-1499 | any | ¥500 |
| 1500-1999 | any | ¥980 |
| 2000+ | any | ¥1,980 |

---

## Rules

- Zenn投稿はGit操作のため冪等（同slugは上書き）
- note投稿はSelenium依存のため、UI変更で壊れる可能性あり
  - エラー時は記事内容をローカル保存してから通知
- 投稿成功時は必ずGoogle Sheetsに記録
- Slack通知失敗はログに記録するが、パイプラインは継続
- 1日あたりの投稿上限を超えないように設定を確認

---

## Error Recovery

1. Zenn push失敗 → git pull --rebase して再試行
2. note Selenium失敗 → スクリーンショット保存 → Slack通知
3. Sheets API失敗 → ローカルJSONにバックアップ記録

---

## Output

Publishing results:
- Platform, title, URL, price (note only)
- Success/failure status per article
- Daily summary stats

---

## STOP CONDITION

- 全合格記事の投稿が完了したら停止。
- 連続投稿失敗3回でそのプラットフォームをスキップ。
