"""Generate KENTO cover images for the three 2026-04-13 note posts and
attach them on note.com.

Standalone because the generic ``retrofit_note_covers.py`` would pick
up every historical note article; here we only want today's three
fixed posts. Reuses:

- :class:`generators.note_cover_generator.NoteCoverGenerator` for the
  PNG generation.
- :func:`scripts.retrofit_note_covers._attach_cover` for the
  Playwright-driven upload flow against the live editor.

Run once:
    venv/Scripts/python.exe scripts/set_today_covers.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from generators.note_cover_generator import NoteCoverGenerator  # noqa: E402
from publishers.note_publisher import NotePublisher  # noqa: E402
from scripts.retrofit_note_covers import _attach_cover  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("set_today_covers")

_COVER_DIR = _REPO / "data" / "images" / "covers"
_COVER_DIR.mkdir(parents=True, exist_ok=True)


TARGETS: list[dict[str, str]] = [
    {
        "slug": "fujin_shimokita",
        "title": "【現地レポ】下北沢の和食居酒屋「風神」",
        "genre": "food",
        "url": "https://note.com/kento_kanazawa/n/n08c2bf51d0b7",
    },
    {
        "slug": "aozora_cafe",
        "title": "【保存版】Bluesky「青空カフェ部」が映す都市カフェ文化",
        "genre": "food",
        "url": "https://note.com/kento_kanazawa/n/n3111501b8657",
    },
    {
        "slug": "yayoiken_shimokita",
        "title": "【本音】「下北沢にやよい軒を誘致してくれ」",
        "genre": "food",
        "url": "https://note.com/kento_kanazawa/n/n086486f8a8d3",
    },
]


def main() -> int:
    gen = NoteCoverGenerator()
    covers: list[tuple[dict[str, str], Path]] = []
    for t in TARGETS:
        out = _COVER_DIR / f"{t['slug']}.png"
        path = gen.generate(title=t["title"], genre=t["genre"], out_path=out)
        logger.info("generated %s", path)
        covers.append((t, path))

    pub = NotePublisher(headless=False)
    failures: list[str] = []
    try:
        for meta, cover_path in covers:
            logger.info("== Attaching cover for %s ==", meta["url"])
            pub._ensure_started()  # reuse existing startup plumbing
            ok = _attach_cover(pub._page, meta["url"], cover_path)
            if ok:
                logger.info("[OK] %s", meta["url"])
            else:
                logger.error("[FAIL] %s", meta["url"])
                failures.append(meta["url"])
    finally:
        pub.close()

    if failures:
        logger.error("cover attach failures: %s", failures)
        return 1
    logger.info("All covers generated and attached successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
