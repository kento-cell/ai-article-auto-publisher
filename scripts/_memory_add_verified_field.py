"""Add `last_verified: YYYY-MM-DD` to every memory file's frontmatter.

Run once to backfill. Future memory writes should include the field
manually. Memory dir lives outside the repo
(~/.claude/projects/<project>/memory/) so this script targets it
directly.

Behavior:
  - Skip MEMORY.md (it's an index, no frontmatter)
  - Skip files that already have `last_verified:`
  - Insert `last_verified: <today>` right after the `description:` line
    in the existing frontmatter block
  - Dry-run by default; pass --apply to write

Why: 30+day-old memory entries are unreliable (see today's Zenn-cap
误诊 incident). A timestamp lets the model judge whether to trust or
re-verify before acting.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path

MEMORY_DIR = Path(os.path.expanduser(
    "~/.claude/projects/E--ai-article-auto-publisher/memory"
))
TODAY = _dt.date.today().isoformat()


def process(path: Path, apply: bool) -> str:
    text = path.read_text(encoding="utf-8")
    if "last_verified:" in text:
        return "skip-already-has"
    # Match frontmatter: --- ... ---
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=re.DOTALL)
    if not m:
        return "skip-no-frontmatter"
    fm_body = m.group(1)
    # Insert last_verified after description: line if present, else
    # append at end of frontmatter body.
    if "description:" in fm_body:
        new_fm = re.sub(
            r"^(description:.*)$",
            rf"\1\nlast_verified: {TODAY}",
            fm_body, count=1, flags=re.MULTILINE,
        )
    else:
        new_fm = fm_body.rstrip() + f"\nlast_verified: {TODAY}"
    new_text = text[:m.start()] + "---\n" + new_fm + "\n---\n" + text[m.end():]
    if apply:
        path.write_text(new_text, encoding="utf-8")
    return "updated"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually write changes (default: dry-run)")
    args = ap.parse_args()
    if not MEMORY_DIR.is_dir():
        print(f"memory dir not found: {MEMORY_DIR}", file=sys.stderr)
        return 1
    counts = {"updated": 0, "skip-already-has": 0, "skip-no-frontmatter": 0}
    for path in sorted(MEMORY_DIR.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        result = process(path, apply=args.apply)
        counts[result] += 1
        print(f"  [{result}] {path.name}")
    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n{mode} — updated={counts['updated']} "
          f"already-has={counts['skip-already-has']} "
          f"no-frontmatter={counts['skip-no-frontmatter']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
