"""Regenerate cover + inline images for today's 4 published note posts
using the ChatGPT Ghibli pipeline, then swap them in via edit_article.

Why a custom script: the existing regen utilities target either
the eyecatch only or pull stock photos from Unsplash. For these 4
articles (published 2026-05-13 with Brave running → ChatGPT bypassed
→ Pollinations/Unsplash fallback) we want both cover AND inline images
re-generated via ChatGPT.

Pre-req: Brave must be fully stopped (`taskkill /F /IM brave.exe`).
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
logger = logging.getLogger("regen_today_note")


# Default targets: when no positional args are given, auto-pick the note articles
# published TODAY (Asia/Tokyo) by walking data/articles/ and filtering by mtime
# and URL host. Old hard-coded TARGETS = [PDRN/シカ/緊急ケア] caused a 6-22 morning
# accident where K-beauty articles from 6-03 were silently re-generated instead of
# today's 4 posts. Keep TARGETS empty so the auto-discovery path is the default.
TARGETS: list[str] = []


def _today_note_targets() -> list[str]:
    """Return article_ids whose JSON was touched today (Asia/Tokyo) and whose
    published_url points to note.com. Falls back to empty list if discovery fails."""
    import datetime as _dt
    articles_dir = _REPO / "data" / "articles"
    if not articles_dir.exists():
        return []
    today_jst = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).date()
    out: list[str] = []
    for path in articles_dir.glob("*.json"):
        try:
            mt = _dt.datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=_dt.timezone(_dt.timedelta(hours=9)),
            ).date()
            if mt != today_jst:
                continue
            d = json.loads(path.read_text(encoding="utf-8"))
            url = (d.get("published_url") or d.get("note_url") or "")
            if "note.com" in url and os.environ.get("NOTE_USER", "") in url:
                out.append(path.stem)
        except Exception:  # noqa: BLE001
            continue
    return sorted(out)


def _kill_brave() -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "brave.exe"],
            check=False, capture_output=True,
        )
        logger.info("brave.exe killed (or was already stopped)")
        time.sleep(2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("kill brave failed: %s", exc)


def _strip_local_images(content: str) -> str:
    """Drop ``![alt](data/images/...)`` markdown so the edit re-uploads
    fresh inline images via the editor's paste handler."""
    return re.sub(
        r"\n?!\[[^\]]*\]\(data/images/[^)\s]+(?:\s+\"[^\"]*\")?\)\n?",
        "\n",
        content,
    )


def main() -> int:
    # CDP attach mode (CHATGPT_CDP_PORT set) needs a LIVE Brave on the
    # debug port — killing it here would force a launch_persistent_context
    # fallback. Only kill when running the old persistent-context path.
    if os.environ.get("CHATGPT_CDP_PORT", "").strip():
        logger.info("CDP mode (port %s) — skip brave kill, attaching instead",
                    os.environ["CHATGPT_CDP_PORT"].strip())
    else:
        _kill_brave()

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

    # Optional style preset + genre hint (e.g. K-beauty regen):
    #   --preset kbeauty_poster   --genre "K-beauty / 韓国コスメ"
    # When --preset is given the cover follows the preset style (if the
    # preset is cover_styled) instead of the default infographic banner.
    argv = sys.argv[1:]
    style_preset: str | None = None
    genre_hint = "general tech / lifestyle"
    consumed: set[str] = set()  # values eaten by space-separated flags
    for i, a in enumerate(argv):
        if a == "--preset" and i + 1 < len(argv):
            style_preset = argv[i + 1]
            consumed.add(argv[i + 1])
        elif a.startswith("--preset="):
            style_preset = a.split("=", 1)[1]
        elif a == "--genre" and i + 1 < len(argv):
            genre_hint = argv[i + 1]
            consumed.add(argv[i + 1])
        elif a.startswith("--genre="):
            genre_hint = a.split("=", 1)[1]

    # Slugs are positional args (not flags, not flag-values); else auto-discover
    # today's note posts; else fall through to (empty) TARGETS.
    positional = [a for a in argv if not a.startswith("-") and a not in consumed]
    if positional:
        targets = positional
    else:
        targets = _today_note_targets() or TARGETS
        if targets:
            logger.info("auto-discovered today's note targets (%d): %s",
                        len(targets), targets)
    if style_preset:
        logger.info("style_preset=%s genre_hint=%s", style_preset, genre_hint)

    articles_dir = _REPO / "data" / "articles"
    jobs: list[dict] = []
    for aid in targets:
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

    # Phase 1 — generate images via ChatGPT (Brave+Playwright)
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
                genre_hint=genre_hint,
                style_preset=style_preset,
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
            # Persist new paths back to store immediately so we don't
            # lose them if the publisher step crashes mid-batch.
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

    # Phase 2 — upload via NotePublisher.edit_article
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
