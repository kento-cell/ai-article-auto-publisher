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

import io
import logging
import os
import re
import subprocess
import sys

# Fix Windows cp932 encoding for Unicode output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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
# Cross-platform venv python path
_venv_scripts = PROJECT_ROOT / "venv" / ("Scripts" if sys.platform == "win32" else "bin")
PYTHON = str(_venv_scripts / ("python.exe" if sys.platform == "win32" else "python"))

# Track running process
_current_process: subprocess.Popen | None = None
_process_lock = threading.Lock()

# Initialize Slack app
app = App(token=BOT_TOKEN)


# ==================================================================
# Security
# ==================================================================

_channel_name_cache: dict[str, str] = {}


def _is_authorized(event: dict) -> bool:
    """Check if the user and channel are authorized."""
    user_id = event.get("user", "")
    if not user_id:
        return False

    channel_name = _get_channel_name(event.get("channel", ""))

    if channel_name != ALLOWED_CHANNEL:
        return False

    # If no whitelist configured, allow all users in the channel
    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        logger.warning("Unauthorized user: %s", user_id)
        return False

    return True


def _get_channel_name(channel_id: str) -> str:
    """Get channel name from channel ID (cached)."""
    if channel_id in _channel_name_cache:
        return _channel_name_cache[channel_id]
    try:
        result = app.client.conversations_info(channel=channel_id)
        name = result["channel"]["name"]
        _channel_name_cache[channel_id] = name
        return name
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

_current_label: str = ""
_is_running: bool = False


def _run_pipeline_sync(say, mode: str, label: str):
    """Run main.py and post progress to Slack."""
    global _current_process, _current_label, _is_running

    # Atomic check-and-set under lock to prevent race condition
    with _process_lock:
        if _is_running:
            say(f"⚠️ *{_current_label}* が実行中です。`stop` で停止できます。")
            return
        _is_running = True
        _current_label = label

    cmd = [PYTHON, "main.py", f"--{mode}"]
    say(f"🚀 *{label}* 開始...")
    start = datetime.now()

    # Log file for this run
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{mode}.log"

    proc = None
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
        last_phase = ""
        with open(log_file, "w", encoding="utf-8") as f:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                output_lines.append(line)
                f.write(line + "\n")
                f.flush()

                # Phase notifications (clean format)
                if "Phase 1" in line or "記事収集" in line:
                    if last_phase != "collect":
                        say("📡 *収集中*... arXiv / Reddit / RSS")
                        last_phase = "collect"
                elif "件収集" in line:
                    msg = line.split("]")[-1].strip().rstrip("収集").strip()
                    say(f"  → {msg}")
                elif "Phase 2" in line or ("生成" in line and "スコア" in line):
                    if last_phase != "generate":
                        say("✍️ *記事生成中*... (Gemma3)")
                        last_phase = "generate"
                elif "Phase 3" in line or ("投稿" in line and "Phase" in line):
                    if last_phase != "publish":
                        say("📤 *投稿中*...")
                        last_phase = "publish"
                elif "トレンドスコア" in line:
                    say("📊 *トレンド分析完了*")
                elif "トップ" in line:
                    parts = line.split("]")[-1].strip()
                    say(f"  → {parts[:150]}")
                elif "スコアリング合格" in line:
                    count = line.split(":")[-1].strip()
                    say(f"✅ スコアリング合格: *{count}*")
                elif "承認待ち" in line:
                    say("📝 承認待ちの記事をSheetsに登録しました")
                elif "再生成開始" in line:
                    parts = line.split("]")[-1].strip()
                    say(f"🔄 {parts[:200]}")
                elif "再生成完了" in line:
                    parts = line.split("]")[-1].strip()
                    say(f"✅ {parts[:200]}")
                elif "再生成後も不合格" in line:
                    parts = line.split("]")[-1].strip()
                    say(f"❌ {parts[:200]}")
                elif "[Researcher]" in line or "[Strategist]" in line or "[Writer]" in line or "[Critic]" in line or "[Coordinator]" in line:
                    parts = line.split("]")[-1].strip()
                    agent = re.search(r'\[(Researcher|Strategist|Writer|Critic|Coordinator)\]', line)
                    if agent and "Response" not in line:
                        say(f"  🤖 {agent.group(1)}: {parts[:150]}")
                elif "[ERROR]" in line or "失敗" in line:
                    msg = line.split("]")[-1].strip()
                    say(f"⚠️ {msg[:200]}")

        proc.wait()
        elapsed = int((datetime.now() - start).total_seconds())

        with _process_lock:
            _current_process = None
            _current_label = ""
            _is_running = False

        if proc.returncode == 0:
            m, s = divmod(elapsed, 60)
            time_str = f"{m}分{s}秒" if m else f"{s}秒"
            say(f"✅ *{label}* 完了 ({time_str})")
            # Check if any articles were registered for approval
            has_pending = any("承認待ち" in l and "記事なし" not in l for l in output_lines)
            _send_sheets_message(say, mode, has_pending=has_pending)
        else:
            last_lines = "\n".join(output_lines[-3:])
            say(
                f"❌ *{label}* 失敗\n"
                f"```{last_lines[:300]}```\n"
                f"詳細は `log` コマンドで確認できます"
            )

    except Exception as e:
        # Ensure child process is killed on error
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)
        with _process_lock:
            _current_process = None
            _current_label = ""
            _is_running = False
        say(f"❌ 実行エラー: {e}")


def _send_sheets_message(say, mode: str, has_pending: bool = False):
    """Send Sheets link with context message."""
    url = _get_sheets_url()
    if not url:
        return

    if mode == "generate" and has_pending:
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
    elif mode == "regenerate":
        say(
            f"🔄 *再生成結果をSheetsで確認してください*\n"
            f"<{url}|Google Sheetsを開く>"
        )
    elif mode == "publish":
        say(f"📤 投稿結果の詳細: <{url}|Google Sheetsで確認>")


# ==================================================================
# Command handlers
# ==================================================================

_BOT_USER_ID: str = ""


def _get_bot_user_id() -> str:
    """Lazy-fetch and cache the bot's own user ID."""
    global _BOT_USER_ID
    if not _BOT_USER_ID:
        try:
            result = app.client.auth_test()
            _BOT_USER_ID = result.get("user_id", "")
        except Exception:
            pass
    return _BOT_USER_ID


@app.event("message")
def handle_message(event: dict, say):
    """Handle incoming messages as commands."""
    # Ignore bot messages (multiple checks for reliability)
    if event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
        return
    if "bot_id" in event:
        return
    if event.get("user") == _get_bot_user_id():
        return

    if not _is_authorized(event):
        return

    raw_text = event.get("text", "").strip().strip("`").strip()
    text = raw_text.lower()

    # Handle delete command with URL argument
    if text.startswith("delete "):
        url = raw_text[len("delete "):].strip()
        _cmd_delete(say, url)
        return

    # Handle edit command: "edit <URL>" - re-apply stored content from ArticleStore
    if text.startswith("edit "):
        url = raw_text[len("edit "):].strip()
        _cmd_edit(say, url)
        return

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
    elif text == "regenerate":
        _cmd_regenerate(say)
    elif text == "learn":
        _cmd_learn(say)
    elif text == "stop":
        _cmd_stop(say)
    elif text == "status":
        _cmd_status(say)
    elif text == "sheets":
        _cmd_sheets(say)
    elif text.startswith("log"):
        _cmd_log(say, text)


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
                        "`regenerate` — 🔄再生成リクエストをマルチエージェントで処理\n"
                        "`collect` — 収集+ランク付けのみ（トークン消費なし）\n"
                        "`dryrun` — 生成+スコアまで（投稿なし）\n\n"
                        "*📤 投稿*\n"
                        "`publish` — Sheetsで承認済みの記事を投稿\n\n"
                        "*🔧 管理*\n"
                        "`status` — 現在の状態確認\n"
                        "`stop` — 実行中のタスクを停止\n"
                        "`sheets` — Sheetsのリンクを表示\n"
                        "`delete <URL>` — note記事を削除\n"
                        "`log` — 直近の実行ログ表示\n"
                        "`log collect` — 収集ログ表示"
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


def _cmd_regenerate(say):
    """Process regeneration requests from Sheets."""
    thread = threading.Thread(
        target=_run_pipeline_sync,
        args=(say, "regenerate", "記事再生成"),
        daemon=True,
    )
    thread.start()


def _cmd_learn(say):
    """Run note learning pipeline."""
    thread = threading.Thread(
        target=_run_pipeline_sync,
        args=(say, "learn", "Note学習"),
        daemon=True,
    )
    thread.start()


def _cmd_edit(say, url: str):
    """Re-apply stored content to an existing note article (preserves impressions)."""
    if not url or "note.com" not in url:
        say("❌ note.comのURLを指定してください\n例: `edit https://note.com/user/n/xxxxx`")
        return

    def _do_edit():
        try:
            import json as _json
            from pathlib import Path as _P
            say(f"✏️ 編集中: {url}")

            # Find matching stored article by URL or title match
            from utils.article_store import ArticleStore
            from publishers.note_publisher import NotePublisher
            import sys
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
            from main import _extract_japanese_title

            store = ArticleStore()
            # Try to find article by checking all stored ones
            target = None
            for slug in store.list_all():
                data = store.load(slug)
                if data and data.get("platform") == "note":
                    target = data
                    break  # For now, edit the most recent note article

            if not target:
                say("❌ 編集対象の記事データが見つかりません")
                return

            content = target.get("content", "")
            title = _extract_japanese_title(content) or target.get("title", "")

            pub = NotePublisher(headless=False)
            success = pub.edit_article(url, new_title=title, new_content=content)
            pub.close()

            if success:
                say(f"✅ 編集完了: {url}")
            else:
                say(f"❌ 編集失敗: {url}")
        except Exception as e:
            say(f"❌ エラー: {e}")

    thread = threading.Thread(target=_do_edit, daemon=True)
    thread.start()


def _cmd_delete(say, url: str):
    """Delete a note article by URL."""
    if not url or "note.com" not in url:
        say("❌ note.comのURLを指定してください\n例: `delete https://note.com/user/n/xxxxx`")
        return

    def _do_delete():
        try:
            say(f"🗑 削除中: {url}")
            from publishers.note_publisher import NotePublisher
            pub = NotePublisher(headless=False)
            success = pub.delete_article(url)
            pub.close()
            if success:
                say(f"✅ 削除完了: {url}")
            else:
                say(f"❌ 削除失敗: {url}\nログ確認してください")
        except Exception as e:
            say(f"❌ エラー: {e}")

    thread = threading.Thread(target=_do_delete, daemon=True)
    thread.start()


def _cmd_dryrun(say):
    """Dry run: generate + score without publishing."""
    thread = threading.Thread(
        target=_run_pipeline_sync,
        args=(say, "dry-run", "ドライラン"),
        daemon=True,
    )
    thread.start()


_VALID_LOG_MODES = {"generate", "collect-only", "dry-run", "publish", "regenerate"}


def _cmd_log(say, text: str):
    """Show recent log entries."""
    parts = text.split()
    mode = parts[1] if len(parts) > 1 else "generate"

    # Validate mode to prevent path traversal (Codex MEDIUM)
    if mode not in _VALID_LOG_MODES:
        say(f"📄 有効なログ: {', '.join(sorted(_VALID_LOG_MODES))}")
        return

    log_file = PROJECT_ROOT / "logs" / f"{mode}.log"

    if not log_file.exists():
        say(f"📄 `{mode}` のログはまだありません。")
        return

    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-30:]
    content = "\n".join(tail)
    say(f"📄 *{mode}.log* (最新{len(tail)}行)\n```{content[:2500]}```")


def _cmd_stop(say):
    """Stop running task."""
    global _current_process, _current_label, _is_running
    with _process_lock:
        proc = _current_process
        if proc and hasattr(proc, "poll") and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            _current_process = None
            _current_label = ""
            _is_running = False
            say("🛑 タスクを停止しました。")
        elif _is_running:
            # Process not yet spawned but pipeline is starting
            _is_running = False
            _current_label = ""
            say("🛑 起動中のタスクを中止しました。")
        else:
            say("ℹ️ 実行中のタスクはありません。")


def _cmd_status(say):
    """Show system status."""
    with _process_lock:
        running = _is_running
        label = _current_label

    status_emoji = f"🔄 実行中 ({label})" if running else "⏸️ アイドル"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Token budget
    token_info = ""
    try:
        if str(PROJECT_ROOT) not in sys.path:
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

    print("Slack Bot starting...", flush=True)
    print(f"  Channel: #{ALLOWED_CHANNEL}", flush=True)
    print(f"  Allowed users: {ALLOWED_USER_IDS or 'all'}", flush=True)

    handler = SocketModeHandler(app, APP_TOKEN)
    print("SocketModeHandler created, connecting...", flush=True)
    handler.start()


if __name__ == "__main__":
    main()
