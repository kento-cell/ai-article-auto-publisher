"""Slack bot for remote control of the article publishing system.

Run this on the desktop PC. Send commands from Slack (phone/browser)
to control article generation and publishing.

Commands (in #ai-publisher channel):
  generate  — 記事生成+スコアリング+Sheets登録
  publish   — 承認済み記事を投稿
  collect   — 収集+ランク付けのみ
  status    — 現在の状態確認
  stop      — 実行中のタスクを停止
  help      — コマンド一覧

Setup:
  1. api.slack.com/apps で App を作成
  2. Socket Mode を有効化
  3. Bot Token + App Token を .env に設定
  4. Event Subscriptions → message.channels を追加
  5. Bot をチャンネルに招待
  6. python bot/slack_bot.py で起動（常駐）

Required pip: slack-bolt
"""

import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
except ImportError:
    print("slack-bolt が未インストールです: pip install slack-bolt")
    sys.exit(1)

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ==================================================================
# Config
# ==================================================================

BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
ALLOWED_CHANNEL = os.getenv("SLACK_CHANNEL_NAME", "ai-publisher")
ALLOWED_USER_IDS = set(
    filter(None, os.getenv("SLACK_ALLOWED_USERS", "").split(","))
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe")

# Track running process
_current_process: subprocess.Popen | None = None
_process_lock = threading.Lock()

# Initialize Slack app
app = App(token=BOT_TOKEN)


# ==================================================================
# Security
# ==================================================================

def _is_authorized(event: dict) -> bool:
    """Check if the user and channel are authorized."""
    channel_name = _get_channel_name(event.get("channel", ""))
    user_id = event.get("user", "")

    if channel_name != ALLOWED_CHANNEL:
        return False

    # If no whitelist configured, allow all users in the channel
    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        logger.warning("Unauthorized user: %s", user_id)
        return False

    return True


def _get_channel_name(channel_id: str) -> str:
    """Get channel name from channel ID."""
    try:
        result = app.client.conversations_info(channel=channel_id)
        return result["channel"]["name"]
    except Exception:
        return ""


def _get_sheets_url() -> str:
    """Get the Google Sheets URL."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if sheet_id:
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    return ""


# ==================================================================
# Pipeline runner
# ==================================================================

def _run_pipeline_sync(say, mode: str, label: str):
    """Run main.py and post progress to Slack."""
    global _current_process

    with _process_lock:
        if _current_process and _current_process.poll() is None:
            say("⚠️ 別のタスクが実行中です。`stop` で停止できます。")
            return

    cmd = [PYTHON, "main.py", f"--{mode}"]
    say(f"🚀 *{label}* 開始...")
    start = datetime.now()

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with _process_lock:
            _current_process = proc

        output_lines: list[str] = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                output_lines.append(line)
                if any(k in line for k in [
                    "フェーズ", "Phase", "完了", "エラー", "スコア",
                    "承認待ち", "投稿完了", "件収集", "件生成",
                ]):
                    say(f"📋 {line[:200]}")

        proc.wait()
        elapsed = (datetime.now() - start).seconds

        with _process_lock:
            _current_process = None

        if proc.returncode == 0:
            say(f"✅ *{label}* 完了（{elapsed}秒）")
            _send_sheets_message(say, mode)
        else:
            last_lines = "\n".join(output_lines[-5:])
            say(
                f"❌ *{label}* 失敗（コード: {proc.returncode}）\n"
                f"```{last_lines[:500]}```"
            )

    except Exception as e:
        with _process_lock:
            _current_process = None
        say(f"❌ 実行エラー: {e}")


def _send_sheets_message(say, mode: str):
    """Send Sheets link with context message."""
    url = _get_sheets_url()
    if not url:
        return

    if mode == "generate":
        say(
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "📊 *承認待ちの記事があります*\n\n"
                            "Google Sheetsでスコアを確認し、\n"
                            "ステータスを「✅承認」に変更してください。\n\n"
                            "承認後に `publish` で投稿できます。"
                        ),
                    },
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📊 Sheets"},
                        "url": url,
                        "action_id": "open_sheets",
                    },
                },
            ]
        )
    elif mode == "publish":
        say(f"📤 投稿結果の詳細: <{url}|Google Sheetsで確認>")


# ==================================================================
# Command handlers
# ==================================================================

@app.event("message")
def handle_message(event: dict, say):
    """Handle incoming messages as commands."""
    # Ignore bot messages
    if event.get("subtype") == "bot_message" or "bot_id" in event:
        return

    if not _is_authorized(event):
        return

    text = event.get("text", "").strip().lower()

    if text == "help":
        _cmd_help(say)
    elif text == "generate":
        _cmd_generate(say)
    elif text == "publish":
        _cmd_publish(say)
    elif text == "collect":
        _cmd_collect(say)
    elif text == "dryrun":
        _cmd_dryrun(say)
    elif text == "stop":
        _cmd_stop(say)
    elif text == "status":
        _cmd_status(say)
    elif text == "sheets":
        _cmd_sheets(say)


def _cmd_help(say):
    """Show command list."""
    say(
        blocks=[
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🤖 AI記事自動生成システム",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*📝 記事生成*\n"
                        "`generate` — 収集→生成→スコアリング→Sheets登録\n"
                        "`collect` — 収集+ランク付けのみ（トークン消費なし）\n"
                        "`dryrun` — 生成+スコアまで（投稿なし）\n\n"
                        "*📤 投稿*\n"
                        "`publish` — Sheetsで承認済みの記事を投稿\n\n"
                        "*🔧 管理*\n"
                        "`status` — 現在の状態確認\n"
                        "`stop` — 実行中のタスクを停止\n"
                        "`sheets` — Sheetsのリンクを表示"
                    ),
                },
            },
        ]
    )


def _cmd_generate(say):
    """Run article generation pipeline."""
    thread = threading.Thread(
        target=_run_pipeline_sync,
        args=(say, "generate", "記事生成+スコアリング"),
        daemon=True,
    )
    thread.start()


def _cmd_publish(say):
    """Publish approved articles."""
    thread = threading.Thread(
        target=_run_pipeline_sync,
        args=(say, "publish", "承認済み記事の投稿"),
        daemon=True,
    )
    thread.start()


def _cmd_collect(say):
    """Collect and rank articles only."""
    thread = threading.Thread(
        target=_run_pipeline_sync,
        args=(say, "collect-only", "記事収集+ランク付け"),
        daemon=True,
    )
    thread.start()


def _cmd_dryrun(say):
    """Dry run: generate + score without publishing."""
    thread = threading.Thread(
        target=_run_pipeline_sync,
        args=(say, "dry-run", "ドライラン"),
        daemon=True,
    )
    thread.start()


def _cmd_stop(say):
    """Stop running task."""
    global _current_process
    with _process_lock:
        if _current_process and _current_process.poll() is None:
            _current_process.terminate()
            _current_process = None
            say("🛑 タスクを停止しました。")
        else:
            say("ℹ️ 実行中のタスクはありません。")


def _cmd_status(say):
    """Show system status."""
    with _process_lock:
        running = (
            _current_process is not None
            and _current_process.poll() is None
        )

    status_emoji = "🔄 実行中" if running else "⏸️ アイドル"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Token budget
    token_info = ""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from utils.token_manager import TokenManager
        tm = TokenManager()
        remaining = tm.get_remaining()
        token_info = f"\n*トークン残:* {remaining:,}"
    except Exception:
        pass

    say(
        f"📊 *システム状態*\n"
        f"*タスク:* {status_emoji}\n"
        f"*時刻:* {now}"
        f"{token_info}"
    )


def _cmd_sheets(say):
    """Show Sheets link."""
    url = _get_sheets_url()
    if url:
        say(f"📊 *Sheets*: <{url}|開く>")
    else:
        say("⚠️ GOOGLE_SHEET_ID が未設定です。")


# ==================================================================
# Entry point
# ==================================================================

def main():
    """Start the Slack bot."""
    if not BOT_TOKEN or not APP_TOKEN:
        print(
            "❌ Slack トークンが未設定です。\n\n"
            ".env に以下を追加してください:\n"
            "  SLACK_BOT_TOKEN=xoxb-...\n"
            "  SLACK_APP_TOKEN=xapp-...\n\n"
            "セットアップ手順:\n"
            "1. https://api.slack.com/apps で App 作成\n"
            "2. Socket Mode を有効化 → App Token (xapp-) 取得\n"
            "3. OAuth & Permissions → Bot Token Scopes:\n"
            "   - chat:write\n"
            "   - channels:read\n"
            "   - channels:history\n"
            "4. Install to Workspace → Bot Token (xoxb-) 取得\n"
            "5. Event Subscriptions → Subscribe to: message.channels\n"
            "6. チャンネル #ai-publisher を作成し、Botを招待"
        )
        sys.exit(1)

    print(f"✅ Slack Bot 起動中...")
    print(f"   チャンネル: #{ALLOWED_CHANNEL}")
    if ALLOWED_USER_IDS:
        print(f"   許可ユーザー: {ALLOWED_USER_IDS}")
    else:
        print(f"   許可ユーザー: 全員（SLACK_ALLOWED_USERS未設定）")

    handler = SocketModeHandler(app, APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    main()
