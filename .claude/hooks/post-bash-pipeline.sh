#!/usr/bin/env bash
# PostToolUse hook on Bash: ensure slack_bot.py is running.
#
# NOTE: this hook previously also killed leftover python.exe running
# main.py, but that fired on run_in_background Bash tool calls — the
# tool returns immediately after spawning py, so the kill landed on
# the pipeline we just started. That caused --generate to die seconds
# after Sheets init with exit 127. Zombie cleanup is now left to the
# pipeline lock's own stale-PID reclaim instead.
input=$(cat)

# Only act when the user just ran main.py --learn or --generate.
case "$input" in
  *"main.py --learn"*|*"main.py --generate"*) ;;
  *) exit 0 ;;
esac

cd /e/ai-article-auto-publisher 2>/dev/null || exit 0

# Ensure slack_bot.py is running (idempotent).
running=$(powershell -NoProfile -Command "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*slack_bot.py*' }).Count" 2>/dev/null | tr -d '[:space:]')

if [[ -z "$running" || "$running" == "0" ]]; then
  mkdir -p tmp_img
  nohup venv/Scripts/python.exe bot/slack_bot.py > tmp_img/slack_bot.log 2>&1 &
  disown 2>/dev/null || true
  echo '{"systemMessage": "🤖 slack_bot started"}'
fi
exit 0
