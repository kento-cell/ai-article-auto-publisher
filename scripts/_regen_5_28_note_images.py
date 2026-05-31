"""Regenerate cover + inline images for the 4 note articles published on
2026-05-28 morning that fell back to Unsplash, using ChatGPT.

Per user request 2026-05-28: K-beauty / Korean-cosmetic articles get
photo-realistic editorial-poster styling (K-Beauty magazine aesthetic,
not the default Ghibli watercolor). The other two articles use the
standard pipeline (infographic cover + Ghibli inline).

The morning publish round failed every ChatGPT batch because Brave's
CDP port wasn't open AND launch_persistent_context died at startup
(exitCode=21, user_data_dir lock vs the user's Brave window). This
script therefore launches Brave in CDP mode itself (allow_launch=True)
so the attach path is available even when AUTO_LAUNCH_BRAVE_CDP=0 in
.env (user-controlled default).

Targets and routing:
  - kc_004 (韓国コスメ買える 4 経路) → poster_batch
  - kb_007 (韓国コスメ起因 肌トラブル 5)  → poster_batch
  - sl_003 (1週間持ち物減)            → standard chatgpt_image_batch
  - Tech CEOs AI psychosis            → standard chatgpt_image_batch

For the poster route we use the ``style_preset="kbeauty_poster"`` arg on
``chatgpt_image_batch`` (generalized 2026-06-01). The preset's
``cover_styled`` flag makes the cover follow the K-Beauty editorial style
instead of the infographic banner, so the standard articles still get the
infographic cover with no per-batch monkey-patch. (Previously this script
swapped ``ChatGPTImageGenerator._build_prompt`` at runtime — see the
staticmethod-descriptor gotcha in that method's docstring.)
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
logger = logging.getLogger("regen_5_28_note")


TARGETS = [
    # (article_id, route)
    ("note-日本で韓国コスメを買える_4_経路__O-d9e7d6f0", "poster"),
    ("note-韓国コスメ起因の肌トラブル_5_パターン-6abb9880", "poster"),
    ("note-1週間で持ち物を1-2割減らせる_丁寧な-1406264b", "standard"),
    ("note-Tech_CEOs_are_appare-e403776c", "standard"),
]


def _ensure_brave_cdp() -> bool:
    from generators.chatgpt_batch_helper import ensure_brave_cdp_listening
    port = int(os.environ.get("CHATGPT_CDP_PORT", "9222"))
    # allow_launch=True forces a Brave kill+relaunch when the port is
    # cold — user explicitly asked for ChatGPT regen so accepting the
    # disruption is in-scope here.
    return ensure_brave_cdp_listening(port, allow_launch=True, timeout=20.0)


def _drop_local_image_md(content: str) -> str:
    """Remove ``![alt](data/images/...)`` markdown so edit_article's
    inline_image_paths route re-uploads fresh ones via note CDN
    (per project_note_inline_image_flow memory: _drop_local_images +
    inline_image_paths is the verified-correct path)."""
    return re.sub(
        r"\n?!\[[^\]]*\]\(data/images/[^)\s]+(?:\s+\"[^\"]*\")?\)\n?",
        "\n",
        content,
    )


def _poster_batch(
    title: str,
    content: str,
    inline_count: int,
    slug_hint: str,
) -> tuple[Path | None, list[Path]]:
    """Run a ChatGPT image batch with K-Beauty poster style for ALL
    slots (cover + inline) via the ``kbeauty_poster`` style preset.

    The preset's ``cover_styled`` flag makes the cover follow the
    editorial style instead of the infographic banner — no per-batch
    monkey-patch of ``_build_prompt`` needed (generalized 2026-06-01)."""
    from generators.chatgpt_batch_helper import chatgpt_image_batch
    return chatgpt_image_batch(
        title=title,
        content=content,
        inline_count=inline_count,
        slug_hint=slug_hint,
        genre_hint="K-beauty / Korean cosmetics editorial",
        style_preset="kbeauty_poster",
    )


def _standard_batch(
    title: str,
    content: str,
    inline_count: int,
    slug_hint: str,
) -> tuple[Path | None, list[Path]]:
    from generators.chatgpt_batch_helper import chatgpt_image_batch
    return chatgpt_image_batch(
        title=title,
        content=content,
        inline_count=inline_count,
        slug_hint=slug_hint,
        genre_hint="general tech / lifestyle",
    )


def main() -> int:
    if not _ensure_brave_cdp():
        logger.error(
            "Brave CDP unavailable — aborting "
            "(run launch_brave_cdp.bat manually)",
        )
        return 1

    from generators.chatgpt_batch_helper import is_chatgpt_image_gen_enabled
    if not is_chatgpt_image_gen_enabled():
        logger.error(
            "ChatGPT image gen disabled (USE_CHATGPT_IMAGES=0). "
            "Set it to 1 in .env or unset.",
        )
        return 1

    from publishers.note_publisher import NotePublisher

    articles_dir = _REPO / "data" / "articles"
    jobs: list[dict] = []
    for aid, route in TARGETS:
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
            "route": route,
            "path": path,
            "data": d,
            "title": d.get("title", ""),
            "content": d.get("content", ""),
            "url": url,
        })

    logger.info("targets: %d (poster=%d standard=%d)",
                len(jobs),
                sum(1 for j in jobs if j["route"] == "poster"),
                sum(1 for j in jobs if j["route"] == "standard"))

    # ----- Phase 1: generate images -----
    for j in jobs:
        logger.info("=" * 70)
        logger.info("[%s] %s", j["route"], j["title"][:60])
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", j["aid"])[:40]
        try:
            if j["route"] == "poster":
                cover, inlines = _poster_batch(
                    title=j["title"], content=j["content"],
                    inline_count=4, slug_hint=f"regen_{slug}",
                )
            else:
                cover, inlines = _standard_batch(
                    title=j["title"], content=j["content"],
                    inline_count=4, slug_hint=f"regen_{slug}",
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("image batch raised: %s", exc)
            cover, inlines = None, []
        j["cover"] = cover
        j["inlines"] = list(inlines or [])
        logger.info("  → cover=%s inlines=%d",
                    bool(cover), len(j["inlines"]))

        if cover or j["inlines"]:
            try:
                j["data"]["_cover_image_before_regen_5_28"] = (
                    j["data"].get("cover_image")
                )
                j["data"]["_inline_images_before_regen_5_28"] = (
                    j["data"].get("inline_images")
                )
                if cover:
                    j["data"]["cover_image"] = str(cover.relative_to(_REPO))
                j["data"]["inline_images"] = [
                    str(p.relative_to(_REPO)) for p in j["inlines"]
                ]
                j["path"].write_text(
                    json.dumps(j["data"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("store write failed for %s: %s",
                               j["aid"], exc)

    # ----- Phase 2: upload via edit_article -----
    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[str] = []
    try:
        for j in jobs:
            if not j.get("cover") and not j.get("inlines"):
                logger.warning("skip %s (no images generated)",
                               j["title"][:40])
                failed.append(j["title"])
                continue
            body = _drop_local_image_md(j["content"]) if j["content"] else None
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
                        str(j["cover"].resolve())
                        if j.get("cover") else None
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
