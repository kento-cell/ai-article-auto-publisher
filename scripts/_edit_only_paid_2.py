"""Edit-only retry: use already-generated ChatGPT images to update note.

After the previous regen run, images are already saved in
data/articles/{aid}.json (cover_image + inline_images fields).
This script skips Phase 1 (image generation) and only does Phase 2
(edit_article upload) with the now-fixed paid-article publish flow.

Pre-req: Brave fully stopped.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("edit_only")


TARGETS = [
    "note-5_Years_and__5M_Late-f1b21453",
    "note-Cisco_s_stock_pops_1-5224bf4f",
]


def _drop_local_image_lines(content: str) -> str:
    return re.sub(
        r"\n?!\[[^\]]*\]\(data/images/[^)\s]+(?:\s+\"[^\"]*\")?\)\n?",
        "\n",
        content,
    )


def main() -> int:
    subprocess.run(
        ["taskkill", "/F", "/IM", "brave.exe"],
        check=False, capture_output=True,
    )
    time.sleep(2)

    from publishers.note_publisher import NotePublisher

    articles_dir = _REPO / "data" / "articles"
    jobs: list[dict] = []
    for aid in TARGETS:
        path = articles_dir / f"{aid}.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        url = d.get("published_url") or d.get("note_url")
        if not url:
            logger.warning("no URL stored for %s — skipping", aid)
            continue
        cover_path = d.get("cover_image")
        inlines = d.get("inline_images") or []
        # Resolve to absolute paths
        cover_abs = str((_REPO / cover_path).resolve()) if cover_path else None
        inline_abs = [str((_REPO / p).resolve()) for p in inlines]
        if cover_abs and not Path(cover_abs).exists():
            logger.warning("cover image missing: %s", cover_abs)
            cover_abs = None
        inline_abs = [p for p in inline_abs if Path(p).exists()]
        jobs.append({
            "aid": aid,
            "url": url,
            "title": d.get("title", ""),
            "content": d.get("content", ""),
            "cover": cover_abs,
            "inlines": inline_abs,
        })

    logger.info("targets: %d", len(jobs))
    for j in jobs:
        logger.info(
            "  %s: cover=%s inlines=%d url=%s",
            j["aid"][:30], bool(j["cover"]), len(j["inlines"]), j["url"],
        )

    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[str] = []
    try:
        for j in jobs:
            body = _drop_local_image_lines(j["content"]) if j["content"] else None
            logger.info("Editing: %s", j["url"])
            try:
                ok = pub.edit_article(
                    url=j["url"],
                    new_title=None,
                    new_content=body,
                    inline_image_paths=j["inlines"] or None,
                    cover_image_path=j["cover"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("  OK: %s", j["title"][:60])
            else:
                failed.append(j["title"])
                logger.error("  FAIL: %s", j["title"][:60])
            time.sleep(4)
    finally:
        pub.close()

    logger.info(
        "DONE — uploaded=%d failed=%d", succeeded, len(failed),
    )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
