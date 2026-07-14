"""One-shot: fix incident #24/#25 damage on the two paid articles
published 2026-07-14 (user decision: fix titles, keep ¥500).

- Projector (n08979e185717): public title started with 【完全無料】 on a
  ¥500 paywalled article; 10 dangling "（出典: ROOMIE — " citations.
- Handy fan (n648136dc2bba): "科学が証明した" claim with zero backing;
  6 dangling citations; zenn-only :::message syntax rendered raw.

Edits BOTH articles in one browser session. Also writes the fixed
title/content back to the local article JSON so RAG/learn never
re-ingests the broken version.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fix_titles_0714")

_REPO = Path(__file__).resolve().parent.parent
_NOTE_USER = os.environ.get("NOTE_USER", "")

_DANGLING_RE = re.compile(r"（出典:\s*ROOMIE\s*[—ー–-]\s*(?=\n|$)", re.MULTILINE)


def _fix_dangling(content: str) -> tuple[str, int]:
    fixed, n = _DANGLING_RE.subn("（出典: ROOMIE）", content)
    return fixed, n


def _strip_zenn_message_blocks(content: str) -> str:
    """Remove zenn-only :::message wrappers, keep the inner text."""
    content = re.sub(r"^:::message( alert)?\s*$\n?", "", content, flags=re.MULTILINE)
    content = re.sub(r"^:::\s*$\n?", "", content, flags=re.MULTILINE)
    return content


TARGETS = [
    {
        "key": "projector",
        "json": _REPO / "data" / "articles" / "note-これ1台でリビングが映画館に_Anker-2d499fd6.json",
        "url": f"https://note.com/{_NOTE_USER}/n/n08979e185717",
        "new_title": "これ1台でリビングが映画館に。Ankerプロジェクター「音の常識」が変わった3つの理由",
        "strip_zenn": False,
    },
    {
        "key": "fan",
        "json": _REPO / "data" / "articles" / "note-3COINSの_コロコロするこれ_をハン-ce08839d.json",
        "url": f"https://note.com/{_NOTE_USER}/n/n648136dc2bba",
        "new_title": "【2026年夏】300円から始める「体温を下げる」3ステップ暑さ対策 — 3COINS×ハンディファン活用術",
        "strip_zenn": True,
    },
]


def main() -> int:
    from publishers.note_publisher import NotePublisher

    pub = NotePublisher()
    failures = 0
    try:
        for t in TARGETS:
            d = json.loads(t["json"].read_text(encoding="utf-8"))
            content = d["content"]
            lines = content.split("\n", 1)
            body = lines[1].lstrip("\n") if len(lines) > 1 else content

            body, n_dangling = _fix_dangling(body)
            if t["strip_zenn"]:
                body = _strip_zenn_message_blocks(body)
            logger.info("[%s] dangling fixed: %d, body=%d chars",
                        t["key"], n_dangling, len(body))

            ok = pub.edit_article(
                url=t["url"],
                new_title=t["new_title"],
                new_content=body,
            )
            logger.info("[%s] edit_article: %s", t["key"], ok)
            if not ok:
                failures += 1
                continue

            # Write back so learn/RAG never re-ingests the broken copy.
            d["title"] = t["new_title"]
            d["content"] = t["new_title"] + "\n\n" + body
            d["fixed_at"] = "2026-07-14"
            d["fix_reason"] = "incident #24 (title) + #25 (dangling citations); price kept"
            t["json"].write_text(
                json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8",
            )
    finally:
        pub.close()
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
