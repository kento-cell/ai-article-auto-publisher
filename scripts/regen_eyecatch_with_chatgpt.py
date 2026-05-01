"""Regenerate the eyecatch (cover) for an already-published note post
using the ChatGPT Ghibli-style image pipeline, then swap it on note.

Why:
  The original publish for these 16 hallucinated articles used wrong
  stock photos for the eyecatch. fix_note_eyecatches.py replaced them
  with the local title-gradient PNGs as a quick fix. The user prefers
  the proper ChatGPT-Ghibli style (memory:
  project_chatgpt_image_pipeline.md, 2026-04-28).

Pipeline per article:
  1. visual_prompt_builder builds a Japanese visual-summary prompt
     from the article title (Gemma3 via local LLM).
  2. ChatGPTImageGenerator.generate() runs Brave + Playwright on the
     fixed share-URL chat and returns a saved PNG path.
  3. NotePublisher.edit_article(cover_image_path=...) deletes the
     existing eyecatch and uploads the new one (uses the now-fixed
     `aria-label="削除"` coordinate-filter strategy).
  4. data/articles/note-*.json `cover_image` is updated to the new
     path so future re-publishes use it.

Pre-requirement (per memory):
  Brave must be FULLY STOPPED before invoking
  (`taskkill /F /IM brave.exe`). The script does this for you.

Usage:
    python scripts/regen_eyecatch_with_chatgpt.py --only "Claude Code のチーム"
    python scripts/regen_eyecatch_with_chatgpt.py --apply --only "Claude Code のチーム"
    python scripts/regen_eyecatch_with_chatgpt.py --apply --all
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
logger = logging.getLogger("regen_eyecatch_with_chatgpt")


def kill_brave() -> None:
    """Brave must be fully stopped or Playwright user_data_dir is locked."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "brave.exe"],
            check=False, capture_output=True,
        )
        logger.info("brave.exe killed (or wasn't running)")
        time.sleep(2)
    except Exception as exc:
        logger.warning("kill_brave failed: %s", exc)


def collect_targets(only: str | None, take_all: bool):
    out = []
    for f in sorted(
        (_REPO / "data" / "articles").glob("note-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = (
            data.get("note_url")
            or data.get("published_url")
            or data.get("url")
            or ""
        )
        if not url:
            continue
        if only and only not in data.get("title", ""):
            continue
        if not only and not take_all:
            continue
        # Only target articles that were part of the hallucination
        # cleanup batch (have the backup field set by
        # fix_hallucinated_images.py).
        if take_all and "_original_content_with_bad_images" not in data:
            continue
        out.append((f, data))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="title substring filter")
    ap.add_argument(
        "--all", action="store_true",
        help="process all 16 hallucination-batch articles",
    )
    ap.add_argument(
        "--genre", default="general tech / lifestyle",
        help="genre_hint passed to visual_prompt_builder",
    )
    args = ap.parse_args()

    if not args.only and not args.all:
        ap.error("specify --only <title> or --all")

    targets = collect_targets(args.only, args.all)
    logger.info("targets: %d", len(targets))
    for f, data in targets:
        logger.info("  %s", data.get("title", "")[:70])

    if not args.apply:
        logger.info("dry run — pass --apply to generate+upload")
        return 0

    # ----- imports deferred until --apply -----
    kill_brave()
    from generators.visual_prompt_builder import build_visual_prompt
    from generators.chatgpt_image_generator import ChatGPTImageGenerator
    from publishers.note_publisher import NotePublisher

    # Reuse one ChatGPTImageGenerator (Brave+Playwright) across all
    # articles — _open_browser/_close_browser handles per-call setup.
    img_gen = ChatGPTImageGenerator(headless=False)

    out_dir = _REPO / "data" / "images" / "covers"
    out_dir.mkdir(parents=True, exist_ok=True)

    generated: list[tuple[Path, dict, Path]] = []
    for f, data in targets:
        title = data.get("title", "")
        logger.info("=" * 70)
        logger.info("generating Ghibli cover: %s", title[:70])
        try:
            prompt = build_visual_prompt(
                title=title,
                section=None,
                genre_hint=args.genre,
            )
        except Exception as exc:
            logger.exception("visual_prompt_builder failed: %s", exc)
            continue
        logger.info("visual prompt: %s", prompt[:200])

        ts = time.strftime("%Y%m%d_%H%M%S")
        slug = f.stem.replace("note-", "").replace(" ", "_")[:32]
        out_path = out_dir / f"chatgpt_regen_{slug}_{ts}.png"

        try:
            saved = img_gen.generate(
                prompt=prompt,
                size="landscape",
                out_path=out_path,
            )
        except Exception as exc:
            logger.exception("ChatGPT generate raised: %s", exc)
            saved = None

        if saved is None or not saved.exists():
            logger.error("FAIL generation: %s", title[:60])
            continue

        # Persist the new cover_image into the article JSON immediately
        # so we don't lose it if the swap step fails.
        data["_cover_image_before_regen"] = data.get("cover_image")
        data["cover_image"] = str(saved.relative_to(_REPO))
        f.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        generated.append((f, data, saved))
        logger.info("OK gen: %s", saved.name)

    # ChatGPT pipeline holds its own Brave context. Now switch to the
    # NotePublisher (separate Playwright instance) for upload.
    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[tuple[str, str]] = []
    try:
        for f, data, cover in generated:
            title = data.get("title", "")
            url = (
                data.get("note_url")
                or data.get("published_url")
                or data.get("url")
            )
            if not url:
                continue
            logger.info("editing eyecatch on note: %s", url)
            try:
                ok = pub.edit_article(
                    url=url,
                    new_title=title,
                    new_content=data.get("content", "") or "",
                    cover_image_path=str(cover.resolve()),
                )
            except Exception as exc:
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("OK upload: %s", title[:60])
            else:
                failed.append((title, url))
                logger.error("FAIL upload: %s", title[:60])
    finally:
        pub.close()

    logger.info("DONE — generated=%d uploaded=%d failed=%d",
                len(generated), succeeded, len(failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
