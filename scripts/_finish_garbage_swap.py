"""Finish the paid-garbage live swap for the 10 articles the overnight
orchestrator skipped when ChatGPT's image quota ran out (~04:00).

Those articles still carry fabricated content live. Eliminating the
fabrication is the priority, so this does a content-replacement
edit_article using the stock (Unsplash) inline images already embedded
in the regenerated body — no ChatGPT image generation. The cover is
left untouched. A later pass can upgrade these 10 to ChatGPT images
once the quota resets.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
logger = logging.getLogger("finish_garbage_swap")

# The 10 articles skipped by the overnight orchestrator (ChatGPT quota).
TARGETS = [
    "note-Cisco_s_stock_pops_1-5224bf4f",
    "note-Louis_Rossmann_taunt-c4a7127a",
    "note-Microsoft_s_Edge_Cop-d04dd4f6",
    "note-PCOS_Is_Officially_R-34291c12",
    "note-Louis_Rossmann_tells-d59475f2",
    "note-Reddit_Starts_Blocki-9e0633a0",
    "note-_Cannot_be_explained-5f05d53b",
    "note-Judge_rules_DOGE_use-b4394f01",
    "note-Cloudflare_lays_off_-68fac977",
    "note-GameStop_CEO_says_eB-0a33f278",
]

_STOCK_RE = re.compile(r"!\[[^\]]*\]\((data/images/[^)\s]+\.(?:jpg|jpeg|png))")


def _stock_paths(content: str) -> list[str]:
    """Absolute paths of the local stock images embedded in the body."""
    out: list[str] = []
    for rel in _STOCK_RE.findall(content):
        p = (_REPO / rel).resolve()
        if p.exists():
            out.append(str(p))
    return out


def main() -> int:
    import subprocess
    subprocess.run(
        ["taskkill", "/F", "/IM", "brave.exe"],
        check=False, capture_output=True,
    )
    time.sleep(2)

    from publishers.note_publisher import NotePublisher

    articles_dir = _REPO / "data" / "articles"
    pub = NotePublisher(headless=False)
    ok = 0
    failed: list[str] = []
    try:
        for aid in TARGETS:
            path = articles_dir / f"{aid}.json"
            if not path.exists():
                logger.warning("missing: %s", aid)
                failed.append(aid)
                continue
            d = json.loads(path.read_text(encoding="utf-8"))
            url = d.get("published_url") or d.get("url")
            content = d.get("content", "")
            if not url or not content:
                logger.warning("no url/content: %s", aid)
                failed.append(aid)
                continue
            inlines = _stock_paths(content)
            logger.info("=" * 64)
            logger.info("Editing %s — %d stock inline image(s)",
                        d.get("title", "")[:50], len(inlines))
            try:
                res = pub.edit_article(
                    url=url,
                    new_title=None,
                    new_content=content,
                    inline_image_paths=inlines or None,
                    cover_image_path=None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("edit_article raised: %s", exc)
                res = False
            if res:
                ok += 1
                logger.info("  OK: %s", aid)
            else:
                failed.append(aid)
                logger.error("  FAIL (verify via og:image): %s", aid)
            time.sleep(4)
    finally:
        pub.close()

    logger.info("DONE — content-swapped=%d failed=%d", ok, len(failed))
    if failed:
        logger.info("failed/uncertain: %s", failed)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
