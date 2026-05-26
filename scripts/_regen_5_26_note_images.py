"""Regenerate cover + inline images for the 5 note articles published on
2026-05-26 using the ChatGPT pipeline, then swap them in via edit_article.

Why a custom script: this morning's publish round had ChatGPT image batch
failures across the board (Brave launch_persistent_context died at startup
with exitCode=21 → Pollinations / Pillow banner / Unsplash fallback for
cover). The user explicitly asked to swap them with ChatGPT-generated
images, and chose CDP mode (vs. taskkill→relaunch) to avoid the same
launch-time crash.

Pre-req:
  - .env has ``CHATGPT_CDP_PORT=9222`` set (verified).
  - This script launches ``scripts/launch_brave_cdp.bat`` itself; existing
    Brave windows will be restarted into CDP mode (Brave's session-restore
    brings tabs back).

Sequence:
  1. Launch Brave with CDP debug port 9222 (subprocess, wait for listen).
  2. For each target: ChatGPT batch (cover + 4 inline), persist new paths
     into data/articles/<aid>.json so a mid-batch crash doesn't lose work.
  3. NotePublisher.edit_article uploads cover + inline to live note.
  4. ``_purge_chatgpt_sidebar.py --apply`` cleans up the throwaway chats
     left behind by the image-gen flow.
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
logger = logging.getLogger("regen_5_26_note")


TARGETS = [
    "note-kbeauty_ingredient_guide",
    "note-Palantir_Gets_an_Ini-f1624832",
    "note-Disney_sued_over_new-e69e1d96",
    "note-朝_30_分で完結する_丁寧な生活_ルー-8f74bf97",
    "note-Pope_Leo_Issues_AI_E-e59478de",
]


def _ensure_brave_cdp() -> bool:
    """Launch Brave in CDP mode if the port isn't already listening.

    Delegates to the shared :func:`ensure_brave_cdp_listening` helper so
    the main pipeline (`_publish_note`) and this one-shot regen script
    use the same launch / wait logic. This script is allowed to
    auto-launch unconditionally — it exists *because* the user wants
    Brave restarted into CDP mode.
    """
    from generators.chatgpt_batch_helper import ensure_brave_cdp_listening

    port = int(os.environ.get("CHATGPT_CDP_PORT", "9222"))
    return ensure_brave_cdp_listening(port, allow_launch=True, timeout=15.0)


def _strip_local_images(content: str) -> str:
    """Drop ``![alt](data/images/...)`` markdown so the edit re-uploads
    fresh inline images via the editor's paste handler."""
    return re.sub(
        r"\n?!\[[^\]]*\]\(data/images/[^)\s]+(?:\s+\"[^\"]*\")?\)\n?",
        "\n",
        content,
    )


def main() -> int:
    if not _ensure_brave_cdp():
        logger.error("Brave CDP unavailable — aborting (run launch_brave_cdp.bat manually)")
        return 1

    from generators.chatgpt_batch_helper import (
        chatgpt_image_batch,
        is_chatgpt_image_gen_enabled,
    )
    from publishers.note_publisher import NotePublisher

    if not is_chatgpt_image_gen_enabled():
        logger.error(
            "ChatGPT image gen disabled (USE_CHATGPT_IMAGES=0). "
            "Set it to 1 in .env or unset the variable."
        )
        return 1

    articles_dir = _REPO / "data" / "articles"
    jobs: list[dict] = []
    for aid in TARGETS:
        path = articles_dir / f"{aid}.json"
        if not path.exists():
            logger.warning("missing store entry: %s", aid)
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        url = d.get("published_url") or d.get("note_url") or d.get("url")
        if not url:
            logger.warning("no URL stored for %s — skipping", aid)
            continue
        jobs.append({
            "aid": aid,
            "path": path,
            "data": d,
            "title": d.get("title", ""),
            "content": d.get("content", ""),
            "url": url,
        })

    logger.info("targets: %d", len(jobs))

    for j in jobs:
        logger.info("=" * 70)
        logger.info("Generating images for: %s", j["title"][:60])
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", j["aid"])[:40]
        try:
            cover, inlines = chatgpt_image_batch(
                title=j["title"],
                content=j["content"],
                inline_count=4,
                slug_hint=f"regen_{slug}",
                genre_hint="general tech / lifestyle",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("chatgpt_image_batch raised: %s", exc)
            cover, inlines = None, []
        j["cover"] = cover
        j["inlines"] = list(inlines or [])
        logger.info(
            "  → cover=%s inlines=%d",
            bool(cover), len(j["inlines"]),
        )
        if cover:
            try:
                j["data"]["_cover_image_before_regen"] = (
                    j["data"].get("cover_image")
                )
                j["data"]["cover_image"] = str(cover.relative_to(_REPO))
                j["data"]["_inline_images_before_regen"] = (
                    j["data"].get("inline_images")
                )
                j["data"]["inline_images"] = [
                    str(p.relative_to(_REPO)) for p in j["inlines"]
                ]
                j["path"].write_text(
                    json.dumps(j["data"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("store write failed for %s: %s", j["aid"], exc)

    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[str] = []
    try:
        for j in jobs:
            if not j.get("cover") and not j.get("inlines"):
                logger.warning("skip %s (no images generated)", j["title"][:40])
                failed.append(j["title"])
                continue
            body = _strip_local_images(j["content"]) if j["content"] else None
            logger.info("Editing: %s", j["url"])
            try:
                ok = pub.edit_article(
                    url=j["url"],
                    new_title=None,
                    new_content=body,
                    inline_image_paths=[
                        str(p.resolve()) for p in j.get("inlines", [])
                    ] or None,
                    cover_image_path=(
                        str(j["cover"].resolve()) if j.get("cover") else None
                    ),
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
        "DONE — generated=%d uploaded=%d failed=%d",
        sum(1 for j in jobs if j.get("cover") or j.get("inlines")),
        succeeded,
        len(failed),
    )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
