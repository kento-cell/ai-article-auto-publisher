"""One-shot: scan diff text from stdin for common PII patterns.

Usage:
    git diff <base>..HEAD | py scripts/_pii_scan_diff.py
    git diff --cached    | py scripts/_pii_scan_diff.py

Generic patterns are built into PATTERNS. Site-specific patterns
(e.g. owner-specific email fragments) live in the gitignored file
``config/pii_scan_extra.json`` so the scanner itself can be checked
into a public repo without revealing PII. The file format is:

    {
      "label": "regex",
      "another-label": "another regex"
    }

If the file is missing, only the generic patterns run.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parent.parent
_EXTRA_PATH = _REPO / "config" / "pii_scan_extra.json"


PATTERNS: dict[str, str] = {
    "email": r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    "phone-jp": r"\b0\d{1,3}-\d{2,4}-\d{4}\b",
    "win-user-path": r"C:\\Users\\[a-zA-Z0-9_]+",
    "win-repo-path": r"E:\\ai-article-auto-publisher",
    "posix-home": r"/c/Users/[a-zA-Z0-9_]+",
    "key-anthropic": r"sk-ant-[a-zA-Z0-9_-]{20,}",
    "key-openai": r"sk-[a-zA-Z0-9_-]{40,}",
    "key-aws": r"AKIA[0-9A-Z]{16}",
    "key-google": r"AIza[0-9A-Za-z_-]{30,}",
}


def _load_extra() -> dict[str, str]:
    if not _EXTRA_PATH.exists():
        return {}
    try:
        return json.loads(_EXTRA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not parse {_EXTRA_PATH}: {exc}", file=sys.stderr)
        return {}


def main() -> int:
    text = sys.stdin.read()
    patterns = dict(PATTERNS)
    patterns.update(_load_extra())

    hits: dict[str, list[str]] = {}
    for name, pat in patterns.items():
        try:
            found = re.findall(pat, text)
        except re.error as exc:
            print(f"[warn] bad regex {name!r}: {exc}", file=sys.stderr)
            continue
        if not found:
            continue
        uniq = sorted(set(found))
        hits[name] = uniq[:5]

    if not hits:
        print("PII scan: CLEAN")
        return 0
    print("PII scan: HITS")
    for k, v in hits.items():
        print(f"  {k}: {v}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
