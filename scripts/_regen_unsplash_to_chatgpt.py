"""Regenerate cover + inline images for today's Unsplash-fallback publishes.

Target articles: 4 note posts published 2026-05-07 with Unsplash covers
(because earlier in the day ChatGPT image gen was rate-limited or
blocked by Memory pollution). For each target:

1. Build the same (cover + 3 inline) prompt set used by the production
   pipeline.
2. Generate images via ChatGPTImageGenerator (CDP attach mode — Brave
   must be running with --remote-debugging-port=9222).
3. Replace cover + inline images on the live note article via
   NotePublisher.edit_article.
4. Notify Slack on completion.

Run with::

    CHATGPT_CDP_PORT=9222 py scripts/_regen_unsplash_to_chatgpt.py --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("regen_unsplash_to_chatgpt")

# Targets identified from data/articles/ JSON published_at >=
# 2026-05-07T07:55 with Unsplash covers (logs/publish_20260507_v7.log).
# Order: smallest content first so a quick win confirms the pipeline
# before tackling the long Codex Projects one.
TARGETS = [
    {
        "label": "row 169 ロボット (1X Neo / Figure / Tesla)",
        "url": "https://note.com/note-user/n/nf7b37ec10fba",
        "json_glob": "note-1X_Neo*-3bb26b2e.json",
        "inline_count": 3,
    },
    {
        "label": "row 172 ChatGPT/Claude Projects/Gem",
        "url": "https://note.com/note-user/n/ncf56b91da74a",
        "json_glob": "note-ChatGPT_Projects*-629ccf33.json",
        "inline_count": 3,
    },
    {
        "label": "row 175 一人飯カウンター 寿司/焼鳥/ラーメン",
        "url": "https://note.com/note-user/n/n0647c5e8f8eb",
        "json_glob": "note-*d21c595d.json",
        "inline_count": 3,
    },
    {
        "label": "row 168 韓国10ステップスキンケア",
        "url": "https://note.com/note-user/n/ncaa0f9d2ce5e",
        "json_glob": "note-*67ec7978.json",
        "inline_count": 3,
    },
]


def _load_target_record(json_glob: str) -> dict | None:
    matches = list((_REPO / "data" / "articles").glob(json_glob))
    if not matches:
        logger.warning("no JSON match for glob %s", json_glob)
        return None
    if len(matches) > 1:
        logger.warning(
            "multiple matches for %s (using first): %s",
            json_glob, [m.name for m in matches],
        )
    try:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("read %s failed: %s", matches[0], exc)
        return None


def _slack_notify(text: str) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return
    try:
        import requests
        requests.post(url, json={"text": text}, timeout=10)
    except Exception as exc:
        logger.warning("Slack notify failed: %s", exc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply", action="store_true",
        help="Actually edit the live notes; without this flag, dry-run only.",
    )
    ap.add_argument(
        "--only", type=int, default=None,
        help="Only process target #N (1-based) — useful for retry of a single failure.",
    )
    args = ap.parse_args()

    # CDP attach is the only supported mode here — we explicitly want
    # Brave to stay alive throughout and never lock the user_data_dir.
    cdp_port = os.environ.get("CHATGPT_CDP_PORT")
    if not cdp_port:
        logger.error(
            "CHATGPT_CDP_PORT env not set — set it to the Brave debug "
            "port (e.g. 9222) before running.",
        )
        return 2

    targets = TARGETS if args.only is None else [TARGETS[args.only - 1]]

    if not args.apply:
        logger.info("DRY RUN — pass --apply to execute")
        for t in targets:
            rec = _load_target_record(t["json_glob"])
            if not rec:
                logger.info("  ✗ %s: JSON not found", t["label"])
                continue
            logger.info(
                "  • %s | url=%s | title=%s",
                t["label"], t["url"], rec.get("title", "")[:60],
            )
        return 0

    from generators.chatgpt_batch_helper import chatgpt_image_batch
    from publishers.note_publisher import NotePublisher

    publisher = NotePublisher()

    succeeded = 0
    failed: list[tuple[str, str]] = []
    for i, t in enumerate(targets, 1):
        logger.info("=" * 60)
        logger.info("[%d/%d] %s", i, len(targets), t["label"])
        rec = _load_target_record(t["json_glob"])
        if not rec:
            failed.append((t["label"], "JSON load failed"))
            continue

        title = rec.get("title", "")
        content = rec.get("content", "") or ""
        slug_hint = (
            (rec.get("article_id") or t["url"].rsplit("/", 1)[-1]).split("?")[0]
        )

        logger.info("generating ChatGPT image batch (1 cover + %d inline)…",
                    t["inline_count"])
        try:
            cover, inlines = chatgpt_image_batch(
                title=title,
                content=content,
                inline_count=t["inline_count"],
                slug_hint=slug_hint,
            )
        except Exception as exc:
            logger.exception("image batch raised: %s", exc)
            failed.append((t["label"], f"image batch: {exc}"))
            continue

        if not cover:
            logger.error("no cover image produced — skipping edit")
            failed.append((t["label"], "no cover image"))
            continue

        logger.info(
            "image batch done: cover=%s inline=%d",
            cover.name, len(inlines),
        )

        logger.info("editing live note article: %s", t["url"])
        try:
            ok = publisher.edit_article(
                url=t["url"],
                cover_image_path=str(cover),
                inline_image_paths=[str(p) for p in inlines] or None,
            )
        except Exception as exc:
            logger.exception("edit_article raised: %s", exc)
            failed.append((t["label"], f"edit_article: {exc}"))
            continue

        if not ok:
            failed.append((t["label"], "edit_article returned False"))
            continue

        succeeded += 1
        # Persist the regen marker on the JSON so we don't re-process.
        rec["images_regenerated_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        rec["regenerated_cover_path"] = str(cover)
        rec["regenerated_inline_paths"] = [str(p) for p in inlines]
        match_path = next(
            iter((_REPO / "data" / "articles").glob(t["json_glob"])),
            None,
        )
        if match_path:
            match_path.write_text(
                json.dumps(rec, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        logger.info("OK %s", t["label"])

    try:
        publisher.close()
    except Exception:
        pass

    logger.info("=" * 60)
    logger.info(
        "DONE — succeeded=%d failed=%d", succeeded, len(failed),
    )
    for label, reason in failed:
        logger.warning("  failed: %s — %s", label, reason)

    summary = (
        f":frame_with_picture: 既投稿{len(targets)}件のUnsplash画像を"
        f"ChatGPT画像で差替え: 成功={succeeded} 失敗={len(failed)}"
    )
    _slack_notify(summary)

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
