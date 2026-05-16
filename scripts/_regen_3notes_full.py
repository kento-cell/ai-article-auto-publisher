"""Regenerate cover + inline images for 3 specific note posts via the
ChatGPT image pipeline, fix their mermaid flow diagrams, then swap
everything in via ``edit_article``.

Context (2026-05-15): these 3 articles were published while the
ChatGPT image generator was broken (image-element selector bug), so
every visual fell back to an Unsplash stock photo. One article also
shipped a mangled mermaid diagram (bare ``[B] [D] [G]`` placeholders)
because the old ``_mermaid_to_ascii`` could not parse ``{decision}`` /
``(rounded)`` node shapes.

This script:
  * loads the 3 target articles from ``data/articles/``,
  * runs the (now fixed) ``NotePublisher._mermaid_to_ascii`` over each
    body so mermaid blocks become clean numbered step lists,
  * generates 1 cover + up to 5 inline images per article via
    ``chatgpt_image_batch`` (CDP-attach mode — Brave stays running),
  * calls ``edit_article`` with ``inline_image_paths`` + the cleaned
    body so note re-hosts the local PNGs under assets.st-note.com.

Differences from ``_regen_today_note_with_chatgpt.py``:
  * 3 fixed targets instead of 4.
  * Does NOT kill Brave — CDP-attach mode (``CHATGPT_CDP_PORT`` in
    ``.env``) requires the running Brave instance.
  * Strips mermaid from the body before upload (via the publisher's
    own ``_mermaid_to_ascii``) so the flow diagram is fixed in place.
  * inline_count=5 to cap ChatGPT quota / runtime on the 8-10 H2
    articles (the batch helper picks the top-priority sections).
  * Lets the publisher handle local-image markdown removal via
    ``_drop_local_images`` — does NOT pre-strip with
    ``_strip_local_images`` (verified-correct route for this repo).
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
logger = logging.getLogger("regen_3notes")


TARGETS = [
    "note-Zero-day_exploit_com-ce4a843a",
    "note-The_AI_Layoff_Bill_I-1ed0597d",
    "note-_Everyone_is_unhappy-f89b5415",
]

# Inline image cap. The articles have 8-10 H2 sections; generating an
# image for every one would burn 90+ minutes and hit the ChatGPT daily
# image quota. The batch helper scores H2 sections by priority and
# keeps the top N — 5 covers the main content without the intro/outro
# frame sections.
INLINE_COUNT = 5


def main() -> int:
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

    cdp_port = os.environ.get("CHATGPT_CDP_PORT")
    if cdp_port:
        logger.info(
            "CDP-attach mode (port %s) — Brave stays running, not killed.",
            cdp_port,
        )
    else:
        logger.warning(
            "CHATGPT_CDP_PORT not set — chatgpt_image_batch will use "
            "launch_persistent_context, which needs Brave fully closed."
        )

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
        content = d.get("content", "") or ""
        # Fix mermaid in the body now so (a) the image prompts see the
        # cleaned text and (b) edit_article uploads the cleaned body.
        # edit_article also runs _mermaid_to_ascii internally — this is
        # idempotent (cleaned text has no ```mermaid blocks left).
        had_mermaid = "```mermaid" in content
        clean_content = NotePublisher._mermaid_to_ascii(content)
        if had_mermaid:
            logger.info(
                "[%s] mermaid block(s) converted to step list", aid,
            )
        jobs.append({
            "aid": aid,
            "path": path,
            "data": d,
            "title": d.get("title", ""),
            "content": clean_content,
            "url": url,
            "had_mermaid": had_mermaid,
        })

    logger.info("targets resolved: %d / %d", len(jobs), len(TARGETS))
    if not jobs:
        logger.error("no resolvable targets — aborting")
        return 1

    # Phase 1 — generate images via ChatGPT (CDP-attached Brave).
    for j in jobs:
        logger.info("=" * 70)
        logger.info("Generating images for: %s", j["title"][:60])
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", j["aid"])[:40]
        try:
            cover, inlines = chatgpt_image_batch(
                title=j["title"],
                content=j["content"],
                inline_count=INLINE_COUNT,
                slug_hint=f"regen3_{slug}",
                genre_hint="general tech / lifestyle",
            )
        except Exception as exc:  # noqa: BLE001 — fail soft per article
            logger.exception("chatgpt_image_batch raised: %s", exc)
            cover, inlines = None, []
        j["cover"] = cover
        j["inlines"] = list(inlines or [])
        logger.info(
            "  -> cover=%s inlines=%d", bool(cover), len(j["inlines"]),
        )
        if cover or j["inlines"]:
            # Persist new paths immediately so a publisher-step crash
            # doesn't lose the generated images.
            try:
                j["data"]["_cover_image_before_regen"] = (
                    j["data"].get("cover_image")
                )
                if cover:
                    j["data"]["cover_image"] = str(cover.relative_to(_REPO))
                j["data"]["_inline_images_before_regen"] = (
                    j["data"].get("inline_images")
                )
                j["data"]["inline_images"] = [
                    str(p.relative_to(_REPO)) for p in j["inlines"]
                ]
                # Persist the mermaid-cleaned body too.
                if j["had_mermaid"]:
                    j["data"]["content"] = j["content"]
                j["path"].write_text(
                    json.dumps(j["data"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("store write failed for %s: %s", j["aid"], exc)

    # Phase 2 — upload via NotePublisher.edit_article. inline_image_paths
    # triggers the publisher's _drop_local_images route (verified-correct
    # for this repo): markdown image refs are stripped and the local PNGs
    # are re-uploaded via ProseMirror's paste handler so note re-hosts
    # them under assets.st-note.com.
    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[str] = []
    try:
        for j in jobs:
            if not j.get("cover") and not j.get("inlines"):
                logger.warning(
                    "skip %s (no images generated)", j["title"][:40],
                )
                failed.append(j["title"])
                continue
            logger.info("Editing: %s", j["url"])
            try:
                ok = pub.edit_article(
                    url=j["url"],
                    new_title=None,
                    new_content=j["content"] or None,
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
                # Known bug: edit_article can return False ("更新ボタンが
                # 見つかりません") even when note saved the changes.
                # Verify externally with og:image after the run.
                failed.append(j["title"])
                logger.error(
                    "  FAIL (verify og:image externally): %s",
                    j["title"][:60],
                )
            time.sleep(5)
    finally:
        pub.close()

    logger.info("=" * 70)
    logger.info(
        "DONE - generated=%d uploaded_ok=%d reported_fail=%d",
        sum(1 for j in jobs if j.get("cover") or j.get("inlines")),
        succeeded,
        len(failed),
    )
    for j in jobs:
        logger.info(
            "  %s | cover=%s inline=%d | %s",
            j["aid"], bool(j.get("cover")), len(j.get("inlines", [])),
            j["url"],
        )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
