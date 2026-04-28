#!/usr/bin/env bash
# One-shot "game mode" toggle: kill or revive the background AI stack.
#
# Usage:
#   bash scripts/game_mode.sh on      # kill everything heavy (game time)
#   bash scripts/game_mode.sh off     # bring slack_bot back up
#   bash scripts/game_mode.sh status  # show what's alive
#
# What "on" stops:
#   - slack_bot.py (persistent Python listener)
#   - any python.exe running main.py (collect/generate/publish pipeline)
#   - Ollama models currently loaded into VRAM (via `ollama ps` + `ollama stop`)
#   - Playwright's managed Chromium (launched by note_publisher)
#
# What "on" does NOT touch:
#   - The Ollama server process itself (idle, tiny — ~50MB).
#     Models unload on `ollama stop` and don't reload until a request comes in.
#   - Your browsers, IDE, or anything not spawned by this project.
#
# "off" starts slack_bot via the same nohup pattern the hook uses; Ollama
# models lazy-load on the next generate call, so no action needed there.

set -u

cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
MODE="${1:-status}"

_green() { printf '\033[32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
_red() { printf '\033[31m%s\033[0m\n' "$*"; }
_dim() { printf '\033[90m%s\033[0m\n' "$*"; }

_count_proc() {
    # $1 = image name, $2 = cmdline substring (optional)
    local image="$1"
    local needle="${2:-}"
    if [ -n "$needle" ]; then
        powershell -NoProfile -Command \
            "@(Get-CimInstance Win32_Process -Filter \"Name='$image'\" | Where-Object { \$_.CommandLine -like '*$needle*' }).Count" \
            2>/dev/null | tr -d '[:space:]'
    else
        powershell -NoProfile -Command \
            "@(Get-CimInstance Win32_Process -Filter \"Name='$image'\").Count" \
            2>/dev/null | tr -d '[:space:]'
    fi
}

_kill_proc() {
    # $1 = image name, $2 = cmdline substring (optional)
    local image="$1"
    local needle="${2:-}"
    if [ -n "$needle" ]; then
        powershell -NoProfile -Command \
            "Get-CimInstance Win32_Process -Filter \"Name='$image'\" | Where-Object { \$_.CommandLine -like '*$needle*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
            2>/dev/null
    else
        powershell -NoProfile -Command \
            "Get-CimInstance Win32_Process -Filter \"Name='$image'\" | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
            2>/dev/null
    fi
}

status() {
    local bot
    bot=$(_count_proc "python.exe" "slack_bot.py")
    local pipeline
    pipeline=$(_count_proc "python.exe" "main.py")
    local chromium
    chromium=$(_count_proc "chrome.exe" "ms-playwright")
    local ollama_server
    ollama_server=$(_count_proc "ollama.exe")

    echo "=== 裏で動いてるもの ==="
    printf "  slack_bot       : %s\n" "${bot:-0}"
    printf "  main.py         : %s\n" "${pipeline:-0}"
    printf "  Playwright UI   : %s\n" "${chromium:-0}"
    printf "  ollama server   : %s\n" "${ollama_server:-0}"

    # Models currently loaded (consume RAM/VRAM)
    if command -v ollama >/dev/null 2>&1; then
        local loaded
        loaded=$(ollama ps 2>/dev/null | tail -n +2 | awk 'NF{print "  - "$1}')
        if [ -n "$loaded" ]; then
            echo "  ollama models   :"
            echo "$loaded"
        else
            echo "  ollama models   : none loaded"
        fi
    fi
}

game_on() {
    _yellow "→ game mode ON: 裏の重いやつを落とします"

    # 1) slack_bot — kill first so PostToolUse hooks don't try to restart it mid-flight
    if [ "$(_count_proc python.exe slack_bot.py)" != "0" ]; then
        _dim "  stopping slack_bot.py"
        _kill_proc "python.exe" "slack_bot.py"
    fi

    # 2) pipeline runs
    if [ "$(_count_proc python.exe main.py)" != "0" ]; then
        _dim "  stopping main.py pipeline"
        _kill_proc "python.exe" "main.py"
    fi

    # 3) Playwright-managed Chromium
    if [ "$(_count_proc chrome.exe ms-playwright)" != "0" ]; then
        _dim "  closing Playwright Chromium"
        _kill_proc "chrome.exe" "ms-playwright"
    fi

    # 4) Unload Ollama models (not the server — just the VRAM/RAM-heavy models)
    if command -v ollama >/dev/null 2>&1; then
        local models
        models=$(ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}')
        for m in $models; do
            _dim "  unloading ollama model: $m"
            ollama stop "$m" 2>/dev/null || true
        done
    fi

    # Remove stale pipeline lock so the next run can start cleanly
    rm -f "$REPO/data/.pipeline.lock" 2>/dev/null || true

    _green "✓ done — ゲーム頑張って"
    echo ""
    status
}

game_off() {
    _yellow "→ game mode OFF: slack_bot を起こします"

    if [ "$(_count_proc python.exe slack_bot.py)" != "0" ]; then
        _green "  slack_bot はもう動いてる"
    else
        mkdir -p "$REPO/tmp_img"
        nohup "$REPO/venv/Scripts/python.exe" "$REPO/bot/slack_bot.py" \
            > "$REPO/tmp_img/slack_bot.log" 2>&1 &
        disown 2>/dev/null || true
        _green "  slack_bot を起動しました"
    fi
    echo ""
    echo "ollama のモデルは次の生成リクエストで自動ロードされます"
    status
}

case "$MODE" in
    on|stop|kill)
        game_on
        ;;
    off|start|wake)
        game_off
        ;;
    status|*)
        status
        ;;
esac
