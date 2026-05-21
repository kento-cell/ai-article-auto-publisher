"""Generic quote-faithfulness checker — pass article slugs as CLI args.

Generalised from _verify_5_21_quotes.py so future cycles can reuse it
without duplicating the boilerplate. Reports FOUND / PARTIAL / NOT FOUND
for each `> "..."` block against the source.content extracted from the
Python-repr 'source' field of the JSON."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
# Python's repr() uses single quotes by default but switches to double
# quotes when the value itself contains an unescaped single quote.
SRC_CONTENT_SINGLE_RE = re.compile(r"'content':\s*'((?:[^'\\]|\\.)*)'")
SRC_CONTENT_DOUBLE_RE = re.compile(r"'content':\s*\"((?:[^\"\\]|\\.)*)\"")
QUOTE_RE = re.compile(r'^>\s*[\"“]([^\"”]+)[\"”]', re.M)


def extract_src_content(raw: str) -> str:
    m = SRC_CONTENT_SINGLE_RE.search(raw)
    if not m:
        m = SRC_CONTENT_DOUBLE_RE.search(raw)
    if not m:
        return ""
    return m.group(1).replace("\\n", " ").replace("\\'", "'")


def verify(slug: str) -> None:
    path = REPO / "data" / "articles" / f"{slug}.json"
    if not path.exists():
        print(f"=== {slug} === NOT FOUND on disk")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_source = data.get("source", "")
    src_content = extract_src_content(raw_source)
    src_norm = re.sub(r"\s+", " ", src_content).lower()
    content = data.get("content", "")
    quotes = QUOTE_RE.findall(content)

    print(f"=== {slug} ===")
    print(f"src_content_len: {len(src_content)} | quotes: {len(quotes)}")
    for q in quotes[:8]:
        qn = re.sub(r"\s+", " ", q).lower().strip()
        full = qn in src_norm
        partial = qn[:50] in src_norm if not full else True
        marker = "FOUND" if full else ("PARTIAL" if partial else "NOT FOUND")
        print(f"  [{marker}] {q[:140]}")
    print()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: _verify_quotes_any.py <slug> [<slug> ...]")
        return 2
    for slug in argv[1:]:
        verify(slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
