#!/usr/bin/env bash
# SessionStart hook — JOURNAL.md rotation when it exceeds threshold.
#
# Fires on every Claude Code session start and on --resume. Cheap
# (just wc + mv). NEVER kill processes here (see memory
# project_hook_crash_bug — PostToolUse Stop-Process had a fatal bug,
# do not repeat the pattern).
#
# Behavior:
#   - If docs/sessions/JOURNAL.md exceeds 500 lines, move it to
#     docs/sessions/archive/YYYY-MM-JOURNAL.md (concat if archive
#     already exists for this month) and start a fresh empty file.
#   - Always exit 0 — never block session start.
#
# Outputs a single line to stderr if rotation happens so the user can
# see it. Otherwise silent.

set -u  # no -e on purpose; never let this hook fail the session start

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || REPO_ROOT="$(pwd)"
JOURNAL="$REPO_ROOT/docs/sessions/JOURNAL.md"
ARCHIVE_DIR="$REPO_ROOT/docs/sessions/archive"

[ -f "$JOURNAL" ] || exit 0

LINES=$(wc -l < "$JOURNAL" 2>/dev/null | tr -d ' ')
[ -z "$LINES" ] && exit 0
[ "$LINES" -le 500 ] && exit 0

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
exit 0
