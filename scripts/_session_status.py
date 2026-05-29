"""Auto-update STATE.md auto-generated sections.

STATE.md has 3 sections fenced by HTML comment markers that this script
overwrites in place:
  - `<!-- AUTO:updated -->...<!-- /AUTO:updated -->`
  - `<!-- AUTO:recent -->...<!-- /AUTO:recent -->`
  - `<!-- AUTO:pipeline -->...<!-- /AUTO:pipeline -->`

Manually-maintained sections (In Flight, Next Actions, Active Backlog,
Known Live Issues, Pointers) are left untouched so human intent is not
clobbered.

Usage:
  py scripts/_session_status.py            # update in place
  py scripts/_session_status.py --print    # print only, don't write

Cheap & idempotent — runs in <5s, safe to call from hooks or chron.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
STATE_PATH = _REPO / "docs" / "sessions" / "STATE.md"


def _now_jst() -> str:
    jst = _dt.timezone(_dt.timedelta(hours=9))
    return _dt.datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")


def _recent_publishes(limit: int = 5) -> list[dict]:
    """Return up to `limit` recently published articles from data/articles/."""
    arts_dir = _REPO / "data" / "articles"
    if not arts_dir.is_dir():
        return []
    out = []
    files = sorted(
        arts_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for f in files[:50]:  # scan up to 50 to find `limit` with URL
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        url = (d.get("published_url") or d.get("note_url") or "").strip()
        if not url:
            continue
        title = (d.get("title", "") or "")[:48]
        # Strip mojibake — published_url may be the readable field even
        # if title is corrupted in the JSON for windows cp932 reasons.
        out.append({
            "title": title,
            "url": url,
            "mtime": f.stat().st_mtime,
        })
        if len(out) >= limit:
            break
    return out


def _git_recent_commits(hours: int = 48, limit: int = 8) -> list[str]:
    """One-line summaries of recent commits."""
    try:
        r = subprocess.run(
            ["git", "log",
             f"--since={hours} hours ago",
             f"-n{limit}",
             "--pretty=format:%h %s"],
            cwd=_REPO, capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if r.returncode != 0:
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def _zenn_queue_head() -> str | None:
    """Zenn API: what slug is the queue currently publishing? None on error."""
    try:
        import urllib.request
        zenn_user = os.environ.get("ZENN_USERNAME", "")
        url = (
            f"https://zenn.dev/api/articles?username={zenn_user}"
            "&order=latest&count=1"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "ai-article-auto-publisher"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        arts = data.get("articles", [])
        if not arts:
            return None
        a = arts[0]
        return f"{a.get('published_at', '?')[:10]} | {a.get('slug', '?')}"
    except Exception:  # noqa: BLE001
        return None


def _journal_lines() -> int:
    p = _REPO / "docs" / "sessions" / "JOURNAL.md"
    if not p.is_file():
        return 0
    return sum(1 for _ in p.read_text(encoding="utf-8").splitlines())


def _build_updated() -> str:
    return _now_jst()


def _build_recent() -> str:
    items = _recent_publishes(limit=5)
    if not items:
        return "- (no recent publishes — data/articles/ has no entries with published_url)"
    return "\n".join(
        f"- [{it['title']}…]({it['url']})" for it in items
    )


def _build_pipeline() -> str:
    journal_n = _journal_lines()
    zenn_head = _zenn_queue_head() or "(probe failed)"
    commits = _git_recent_commits(hours=48, limit=5)
    commits_str = (
        "\n".join(f"  - {c}" for c in commits)
        if commits else "  - (no commits in last 48h)"
    )
    return (
        f"- JOURNAL.md: {journal_n} lines "
        f"(rotation at 500 via SessionStart hook)\n"
        f"- Zenn queue head (slow-walk): {zenn_head}\n"
        f"- Recent commits (last 48h):\n{commits_str}"
    )


_MARKERS = {
    "updated":  ("<!-- AUTO:updated -->",  "<!-- /AUTO:updated -->"),
    "recent":   ("<!-- AUTO:recent -->",   "<!-- /AUTO:recent -->"),
    "pipeline": ("<!-- AUTO:pipeline -->", "<!-- /AUTO:pipeline -->"),
}


def _replace_section(text: str, name: str, body: str) -> str:
    start, end = _MARKERS[name]
    pat = re.compile(
        re.escape(start) + r".*?" + re.escape(end),
        flags=re.DOTALL,
    )
    repl = f"{start}\n{body}\n{end}"
    if pat.search(text):
        return pat.sub(repl, text)
    # Section missing — append at end, user can move it.
    return text + f"\n\n## (auto-added section: {name})\n{repl}\n"


def update_state(state_path: Path = STATE_PATH, write: bool = True) -> str:
    if not state_path.exists():
        raise SystemExit(f"STATE.md not found: {state_path}")
    text = state_path.read_text(encoding="utf-8")
    text = _replace_section(text, "updated", _build_updated())
    text = _replace_section(text, "recent", _build_recent())
    text = _replace_section(text, "pipeline", _build_pipeline())
    if write:
        state_path.write_text(text, encoding="utf-8")
    return text


def update_state_quick(state_path: Path = STATE_PATH) -> str:
    """Faster variant that skips network-bound sections (Zenn API).

    Use from SessionStart hook where 2-5s of network latency is unwanted."""
    text = state_path.read_text(encoding="utf-8")
    text = _replace_section(text, "updated", _build_updated())
    text = _replace_section(text, "recent", _build_recent())
    # _build_pipeline includes a Zenn API call; for quick mode rebuild
    # without it.
    journal_n = _journal_lines()
    commits = _git_recent_commits(hours=48, limit=5)
    commits_str = (
        "\n".join(f"  - {c}" for c in commits)
        if commits else "  - (no commits in last 48h)"
    )
    pipeline_quick = (
        f"- JOURNAL.md: {journal_n} lines "
        f"(rotation at 500 via SessionStart hook)\n"
        f"- Zenn queue head: (skipped in quick mode — run "
        f"`py scripts/_session_status.py` for full probe)\n"
        f"- Recent commits (last 48h):\n{commits_str}"
    )
    text = _replace_section(text, "pipeline", pipeline_quick)
    state_path.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print", action="store_true",
                    help="print result instead of writing")
    ap.add_argument("--quick", action="store_true",
                    help="skip Zenn API probe (use from SessionStart hook)")
    args = ap.parse_args()
    if args.quick:
        result = update_state_quick()
    else:
        result = update_state(write=not args.print)
    if args.print:
        sys.stdout.write(result)
    else:
        print(f"updated {STATE_PATH.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
