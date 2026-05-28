#!/usr/bin/env bash
# SessionStart hook — runs on every CC session start / --resume.
#
# Two responsibilities:
#   1. Rotate JOURNAL.md → archive/YYYY-MM-JOURNAL.md when > 500 lines
#   2. Refresh STATE.md auto sections (--quick mode, skips network)
#
# Both are non-fatal. NEVER kill processes here (see memory
# project_hook_crash_bug — PostToolUse Stop-Process had a fatal bug,
# do not repeat the pattern).

set -u  # no -e on purpose; never let this hook fail the session start

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || REPO_ROOT="$(pwd)"
JOURNAL="$REPO_ROOT/docs/sessions/JOURNAL.md"
ARCHIVE_DIR="$REPO_ROOT/docs/sessions/archive"

# ---- 1. JOURNAL.md rotation when oversized -------------------------
if [ -f "$JOURNAL" ]; then
    LINES=$(wc -l < "$JOURNAL" 2>/dev/null | tr -d ' ')
    if [ -n "$LINES" ] && [ "$LINES" -gt 500 ]; then
        mkdir -p "$ARCHIVE_DIR" 2>/dev/null
        TS=$(date +%Y-%m)
        ARCHIVE_FILE="$ARCHIVE_DIR/${TS}-JOURNAL.md"
        if [ -f "$ARCHIVE_FILE" ]; then
            printf "\n\n---\n\n" >> "$ARCHIVE_FILE"
            cat "$JOURNAL" >> "$ARCHIVE_FILE"
        else
            cp "$JOURNAL" "$ARCHIVE_FILE"
        fi
        cat > "$JOURNAL" <<'EOF'
# JOURNAL — Append-Only Session Log

> Append today's session work here. Auto-rotated to
> `docs/sessions/archive/YYYY-MM-JOURNAL.md` by SessionStart hook when
> line count exceeds 500. Past months live in `archive/`. **This file
> is NOT auto-read on startup** — use STATE.md for current state,
> Read this only when you need decision provenance.

EOF
        echo "[session-start] rotated JOURNAL.md ($LINES lines) -> $ARCHIVE_FILE" >&2
    fi
fi

# ---- 2. STATE.md auto-section refresh (--quick = skip Zenn API) ----
# Failure is non-fatal — we just won't have fresh auto sections this start.
if command -v py >/dev/null 2>&1; then
    py "$REPO_ROOT/scripts/_session_status.py" --quick >/dev/null 2>&1 || true
elif command -v python >/dev/null 2>&1; then
    python "$REPO_ROOT/scripts/_session_status.py" --quick >/dev/null 2>&1 || true
fi

exit 0
