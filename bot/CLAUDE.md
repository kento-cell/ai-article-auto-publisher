# Slack Bot — 遠隔操作コマンド

bot/ 配下を触った時のみロード。 #ai-publisher チャンネルでのリモート
コマンド一覧。

| コマンド | 動作 |
|---------|------|
| `generate` | 収集→生成→スコアリング→Sheets登録 |
| `publish` | 承認済み記事を投稿 |
| `collect` | 収集+ランクのみ |
| `dryrun` | 生成+スコアまで (Sheets/投稿なし) |
| `stop` | 実行中タスク停止 |
| `status` | 状態確認 |
| `sheets` | Sheets リンク表示 |
| `help` | コマンド一覧 |
