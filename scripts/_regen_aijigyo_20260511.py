"""Regen cover + inline images for the 7 AI×副業 note articles
published 2026-05-11.

Root cause: ``--publish`` was launched without ``CHATGPT_CDP_PORT=9222``
in its env, so ``is_brave_running()`` triggered the "ChatGPT path blocked"
kill-switch and all 7 covers fell back to Unsplash/Pexels. Content and
hallucination scoring are fine; only the visuals need replacing.

Run (Brave CDP at 9222 must already be live)::

    CHATGPT_CDP_PORT=9222 py scripts/_regen_aijigyo_20260511.py --apply

Order: shortest content first (Notion テンプレ) so the pipeline self-checks
before tackling the longer pieces. Each article gets 1 cover + 4 inline
images matching the production publisher's count.
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
logger = logging.getLogger("regen_aijigyo_20260511")

TARGETS = [
    {
        "label": "Notion テンプレ販売",
        "url": "https://note.com/note-user/n/n23e80eccf80a",
        "json_glob": "note-Notion_AIで作る_売れるテンプレ-d359c01b.json",
        "inline_count": 4,
    },
    {
        "label": "AI副業 30日ロードマップ",
        "url": "https://note.com/note-user/n/n62eacb493a24",
        "json_glob": "note-完全未経験から_AI_副業で月5万円ライ-d37ac2bc.json",
        "inline_count": 4,
    },
    {
        "label": "Dify / Voiceflow チャットボット代行",
        "url": "https://note.com/note-user/n/n3d77ed23d430",
        "json_glob": "note-Dify___Voiceflow_を中心-7a6b7a41.json",
        "inline_count": 4,
    },
    {
        "label": "Make / Zapier / n8n",
        "url": "https://note.com/note-user/n/ne612381fbe4a",
        "json_glob": "note-Make___Zapier___n8n_-be348e72.json",
        "inline_count": 4,
    },
    {
        "label": "Perplexity / Felo / GenSpark リサーチ代行",
        "url": "https://note.com/note-user/n/n55aa7048484a",
        "json_glob": "note-Perplexity___Felo___-0d7d9b69.json",
        "inline_count": 4,
    },
    {
        "label": "AI ライティング副業",
        "url": "https://note.com/note-user/n/n9ebe0e94476c",
        "json_glob": "note-AI_ライティングを武器に_低単価ライテ-14b5d1c1.json",
        "inline_count": 4,
    },
    {
        "label": "Gumroad プロンプト集販売",
        "url": "https://note.com/note-user/n/na1981bb8adbe",
        "json_glob": "note-Gumroad_で_AI_プロンプト集_-9f03b6e2.json",
        "inline_count": 4,
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

    cdp_port = os.environ.get("CHATGPT_CDP_PORT")
    if not cdp_port:
        logger.error(
            "CHATGPT_CDP_PORT env not set — set it to the Brave debug "
            "port (e.g. 9222) before running.",
        )
        return 2

    targets = TARGETS if args.only is None else [TARGETS[args.only - 1]]

    if not args.apply:
        logger.info("DRY RUN - pass --apply to execute")
        for t in targets:
            rec = _load_target_record(t["json_glob"])
            if not rec:
                logger.info("  X %s: JSON not found", t["label"])
                continue
            logger.info(
                "  - %s | url=%s | title=%s",
                t["label"], t["url"], rec.get("title", "")[:60],
            )
        return 0

    # Make sure the game-homage style stays applied for this batch —
    # caller env should set IMAGE_STYLE_PACK=game_homage, but default
    # to it here so a hand-typed CLI doesn't lose the consistency.
    os.environ.setdefault("IMAGE_STYLE_PACK", "game_homage")

    from generators.chatgpt_batch_helper import chatgpt_image_batch

    # IMPORTANT: ChatGPT image gen uses Playwright Sync API; NotePublisher's
    # edit_article uses Playwright Async (asyncio). Once asyncio loop is
    # started in the process, the Sync API refuses to run. So we do TWO
    # phases: (1) generate ALL images first (no Async-Playwright in scope),
    # then (2) open NotePublisher once and edit ALL articles.
    # Observed 2026-05-11: interleaving the two API modes per-iteration
    # caused 6/7 silent failures with cover=False after the first article.

    # Skip targets that already have a regenerated image set on file —
    # supports resume after a partial failure.
    skipped_resume: list[str] = []
    pending: list[tuple[dict, dict]] = []  # (target, record)
    for t in targets:
        rec = _load_target_record(t["json_glob"])
        if not rec:
            continue
        if rec.get("images_regenerated_at"):
            skipped_resume.append(t["label"])
            continue
        pending.append((t, rec))

    if skipped_resume:
        logger.info(
            "skipping %d already-regenerated target(s): %s",
            len(skipped_resume), ", ".join(skipped_resume),
        )

    # ---- Phase 1: image generation (all targets, sync Playwright only)
    logger.info("=" * 60)
    logger.info("PHASE 1: ChatGPT image generation for %d target(s)", len(pending))
    image_results: list[tuple[dict, dict, Path, list[Path]]] = []
    failed: list[tuple[str, str]] = []
    for i, (t, rec) in enumerate(pending, 1):
        logger.info("-" * 60)
        logger.info("[image %d/%d] %s", i, len(pending), t["label"])
        title = rec.get("title", "")
        content = rec.get("content", "") or ""
        slug_hint = (
            (rec.get("article_id") or t["url"].rsplit("/", 1)[-1]).split("?")[0]
        )
        try:
            cover, inlines = chatgpt_image_batch(
                title=title,
                content=content,
                inline_count=t["inline_count"],
                slug_hint=slug_hint,
                genre_hint="AI副業 / マネタイズ / 個人事業",
            )
        except Exception as exc:
            logger.exception("image batch raised: %s", exc)
            failed.append((t["label"], f"image batch: {exc}"))
            continue
        if not cover:
            logger.error("no cover image produced - skipping target")
            failed.append((t["label"], "no cover image"))
            continue
        logger.info(
            "image batch done: cover=%s inline=%d",
            cover.name, len(inlines),
        )
        image_results.append((t, rec, cover, inlines))

    # ---- Phase 2: live note edits (async Playwright via NotePublisher)
    if not image_results:
        logger.warning("no image batches succeeded - skipping Phase 2")
        succeeded = 0
    else:
        logger.info("=" * 60)
        logger.info(
            "PHASE 2: editing %d live note article(s) via NotePublisher",
            len(image_results),
        )
        from publishers.note_publisher import NotePublisher
        publisher = NotePublisher()
        succeeded = 0
        for i, (t, rec, cover, inlines) in enumerate(image_results, 1):
            logger.info("-" * 60)
            logger.info("[edit %d/%d] %s", i, len(image_results), t["label"])
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
        "DONE - succeeded=%d failed=%d", succeeded, len(failed),
    )
    for label, reason in failed:
        logger.warning("  failed: %s - %s", label, reason)

    summary = (
        f":frame_with_picture: 2026-05-11 AI×副業 7記事の画像を"
        f"ChatGPT画像で差替え: 成功={succeeded} 失敗={len(failed)}"
    )
    _slack_notify(summary)

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
