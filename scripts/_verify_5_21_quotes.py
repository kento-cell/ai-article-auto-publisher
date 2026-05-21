"""One-shot: verify quote faithfulness for 2026-05-21 generate articles
(Grandma + Town) by comparing > "..." quotes against source.content."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent

# Match source.content value inside the Python-repr 'source' string
SRC_CONTENT_RE = re.compile(
    r"'content':\s*'((?:[^'\\]|\\.)*)'",
)
# Match quote blocks: > "..." or > "..."
QUOTE_RE = re.compile(r'^>\s*[\"“]([^\"”]+)[\"”]', re.M)


def main() -> None:
    slugs = [
        "note-An_81-Year-Old_Grand-79373251",
        "note-After_Town_Bans_Floc-fc6cf4a1",
    ]
    for slug in slugs:
        path = REPO / "data" / "articles" / f"{slug}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_source = data["source"]
        m = SRC_CONTENT_RE.search(raw_source)
        src_content = m.group(1) if m else ""
        # The Python-repr string has \n / \' escapes — decode them
        src_content = src_content.replace("\\n", " ").replace("\\'", "'")
        src_norm = re.sub(r"\s+", " ", src_content).lower()

        content = data["content"]
        quotes = QUOTE_RE.findall(content)

        print(f"=== {slug} ===")
        print(f"src_content_len: {len(src_content)}")
        print(f"src head: {src_content[:250]}")
        print(f"引用数: {len(quotes)}")
        for q in quotes[:6]:
            qn = re.sub(r"\s+", " ", q).lower().strip()
            full = qn in src_norm
            partial = qn[:50] in src_norm if not full else True
            marker = "FOUND" if full else ("PARTIAL" if partial else "NOT FOUND")
            print(f"  [{marker}] {q[:140]}")
        print()


if __name__ == "__main__":
    main()
