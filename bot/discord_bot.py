"""Discord bot for remote control of the article publishing system.

Run this on the desktop PC. Send commands from any Discord client
(phone, browser, etc.) to control article generation and publishing.

Commands:
  !generate  — 記事生成+スコアリング+Sheets登録
  !publish   — 承認済み記事を投稿
  !collect   — 収集+ランク付けのみ
  !status    — 現在の状態確認
  !stop      — 実行中のタスクを停止
  !help      — コマンド一覧

Setup:
  1. Discord Developer Portal で Bot を作成
  2. Bot Token を .env の DISCORD_BOT_TOKEN に設定
  3. Bot をサーバーに招待
  4. python bot/discord_bot.py で起動（常駐）
"""

import asyncio
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    import discord
    from discord.ext import commands
except ImportError:
    print("discord.py が未インストールです: pip install discord.py")
    sys.exit(1)

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
ALLOWED_CHANNEL = os.getenv("DISCORD_CHANNEL_NAME", "ai-publisher")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe")

# Track running process
_current_process: subprocess.Popen | None = None
_process_lock = threading.Lock()


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# ==================================================================
# Helpers
# ==================================================================

def _is_allowed_channel(ctx: commands.Context) -> bool:
    """Check if the command is in the designated channel."""
    return ctx.channel.name == ALLOWED_CHANNEL


async def _run_pipeline(ctx: commands.Context, mode: str, label: str):
    """Run main.py in a subprocess and stream output to Discord."""
    global _current_process

    with _process_lock:
        if _current_process and _current_process.poll() is None:
            await ctx.send("⚠️ 別のタスクが実行中です。`!stop` で停止できます。")
            return

    cmd = [PYTHON, "main.py", f"--{mode}"]
    await ctx.send(f"🚀 **{label}** 開始...")
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
                # Send progress updates for key lines
                if any(k in line for k in [
                    "フェーズ", "Phase", "完了", "エラー", "スコア",
                    "承認待ち", "投稿完了", "件収集", "件生成",
                ]):
                    await ctx.send(f"📋 {line[:200]}")

        proc.wait()
        elapsed = (datetime.now() - start).seconds

        with _process_lock:
            _current_process = None

        if proc.returncode == 0:
            await ctx.send(
                f"✅ **{label}** 完了（{elapsed}秒）"
            )
        else:
            last_lines = "\n".join(output_lines[-5:])
            await ctx.send(
                f"❌ **{label}** 失敗（コード: {proc.returncode}）\n"
                f"```\n{last_lines[:500]}\n```"
            )

    except Exception as e:
        with _process_lock:
            _current_process = None
        await ctx.send(f"❌ 実行エラー: {e}")


# ==================================================================
# Commands
# ==================================================================

@bot.event
async def on_ready():
    """Bot起動時のログ出力。"""
    logger.info("Discord Bot 起動: %s", bot.user)
    print(f"✅ Bot起動: {bot.user} (サーバー: {len(bot.guilds)})")


@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    """コマンド一覧を表示。"""
    if not _is_allowed_channel(ctx):
        return

    embed = discord.Embed(
        title="🤖 AI記事自動生成システム",
        description="Discord経由でデスクトップを遠隔操作",
        color=0x5865F2,
    )
    embed.add_field(
        name="📝 記事生成",
        value=(
            "`!generate` — 収集→生成→スコアリング→Sheets登録\n"
            "`!collect` — 収集+ランク付けのみ（トークン消費なし）\n"
            "`!dryrun` — 生成+スコアまで（投稿なし）"
        ),
        inline=False,
    )
    embed.add_field(
        name="📤 投稿",
        value="`!publish` — Sheetsで承認済みの記事を投稿",
        inline=False,
    )
    embed.add_field(
        name="🔧 管理",
        value=(
            "`!status` — 現在の状態確認\n"
            "`!stop` — 実行中のタスクを停止\n"
            "`!sheets` — Sheetsのリンクを表示"
        ),
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="generate")
async def generate(ctx: commands.Context):
    """記事を生成してSheetsに登録する。"""
    if not _is_allowed_channel(ctx):
        return
    await _run_pipeline(ctx, "generate", "記事生成+スコアリング")


@bot.command(name="publish")
async def publish(ctx: commands.Context):
    """承認済み記事を投稿する。"""
    if not _is_allowed_channel(ctx):
        return
    await _run_pipeline(ctx, "publish", "承認済み記事の投稿")


@bot.command(name="collect")
async def collect(ctx: commands.Context):
    """記事を収集してランク付けする（トークン消費なし）。"""
    if not _is_allowed_channel(ctx):
        return
    await _run_pipeline(ctx, "collect-only", "記事収集+ランク付け")


@bot.command(name="dryrun")
async def dryrun(ctx: commands.Context):
    """生成+スコアリングまで実行（投稿なし）。"""
    if not _is_allowed_channel(ctx):
        return
    await _run_pipeline(ctx, "dry-run", "ドライラン")


@bot.command(name="stop")
async def stop(ctx: commands.Context):
    """実行中のタスクを停止する。"""
    if not _is_allowed_channel(ctx):
        return

    global _current_process
    with _process_lock:
        if _current_process and _current_process.poll() is None:
            _current_process.terminate()
            _current_process = None
            await ctx.send("🛑 タスクを停止しました。")
        else:
            await ctx.send("ℹ️ 実行中のタスクはありません。")


@bot.command(name="status")
async def status(ctx: commands.Context):
    """現在の状態を表示する。"""
    if not _is_allowed_channel(ctx):
        return

    with _process_lock:
        running = (
            _current_process is not None
            and _current_process.poll() is None
        )

    embed = discord.Embed(
        title="📊 システム状態",
        color=0x57F287 if not running else 0xFEE75C,
    )
    embed.add_field(
        name="タスク",
        value="🔄 実行中" if running else "⏸️ アイドル",
        inline=True,
    )
    embed.add_field(
        name="時刻",
        value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        inline=True,
    )

    # Token budget
    try:
        from utils.token_manager import TokenManager
        tm = TokenManager()
        remaining = tm.get_remaining()
        embed.add_field(
            name="トークン残",
            value=f"{remaining:,}",
            inline=True,
        )
    except Exception:
        pass

    await ctx.send(embed=embed)


@bot.command(name="sheets")
async def sheets_link(ctx: commands.Context):
    """Google SheetsのURLを表示する。"""
    if not _is_allowed_channel(ctx):
        return

    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if sheet_id:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        await ctx.send(f"📊 **Sheets**: {url}")
    else:
        await ctx.send("⚠️ GOOGLE_SHEET_ID が未設定です。")


# ==================================================================
# Entry point
# ==================================================================

def main():
    """Bot を起動する。"""
    if not TOKEN:
        print(
            "❌ DISCORD_BOT_TOKEN が未設定です。\n"
            ".env に DISCORD_BOT_TOKEN=your_token を追加してください。\n\n"
            "Bot作成手順:\n"
            "1. https://discord.com/developers/applications\n"
            "2. New Application → Bot → Token をコピー\n"
            "3. OAuth2 → URL Generator → bot + Send Messages + Read Messages\n"
            "4. 生成されたURLでサーバーに招待"
        )
        sys.exit(1)

    bot.run(TOKEN)


if __name__ == "__main__":
    main()
