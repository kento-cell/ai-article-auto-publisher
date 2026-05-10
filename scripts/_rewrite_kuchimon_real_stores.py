"""Rewrite the placeholder one-fish-meal note article with real-store content.

Target URL: https://note.com/note-user/n/n0647c5e8f8eb
Source markdown: data/articles/_drafts/rewrite_n0647c5e8f8eb_real_stores.md

Replaces the title + body with researched, real-store, real-review-quoting
content. Cover/inline images are NOT touched (next-day quota reset will
handle image upgrades separately).

Pre-condition: Brave is CLOSED (NotePublisher uses launch_persistent_context
so a running Brave would hold the user_data_dir lock).
"""
from __future__ import annotations

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
logger = logging.getLogger("rewrite_kuchimon")

URL = "https://note.com/note-user/n/n0647c5e8f8eb"
DRAFT = (
    _REPO / "data" / "articles" / "_drafts"
    / "rewrite_n0647c5e8f8eb_real_stores.md"
)


def main() -> int:
    if not DRAFT.exists():
        logger.error("draft markdown not found: %s", DRAFT)
        return 2
    raw = DRAFT.read_text(encoding="utf-8")

    # Pull the H1 as the new title; rest is the body.
    lines = raw.splitlines()
    title_line_idx = next(
        (i for i, ln in enumerate(lines) if ln.startswith("# ")), None,
    )
    if title_line_idx is None:
        logger.error("draft has no H1 title line")
        return 3
    new_title = lines[title_line_idx][2:].strip()
    new_content = "\n".join(lines[title_line_idx + 1:]).lstrip("\n")

    logger.info("new title: %s", new_title)
    logger.info("new body: %d chars", len(new_content))

    from publishers.note_publisher import NotePublisher

    pub = NotePublisher()
    try:
        ok = pub.edit_article(
            url=URL,
            new_title=new_title,
            new_content=new_content,
            # Do NOT pass inline_image_paths — current images stay,
            # so existing Unsplash images remain. Tomorrow's regen
            # will swap them out.
        )
    finally:
        try:
            pub.close()
        except Exception:
            pass

    if not ok:
        logger.error("edit_article returned False")
        return 4

    # Persist a record so future audits can verify what changed.
    rec_path = (
        _REPO / "data" / "articles"
        / f"note-rewrite-n0647c5e8f8eb-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    rec_path.write_text(
        json.dumps(
            {
                "target_url": URL,
                "rewrote_at": datetime.now(timezone.utc).isoformat(),
                "new_title": new_title,
                "new_content_len": len(new_content),
                "draft_source": str(DRAFT.relative_to(_REPO)),
                "changes": (
                    "placeholder store names (○○/××/□□/△△) replaced "
                    "with 9 real verified stores; reviews summarised "
                    "from tabelog/retty/sushilog/takemashuran"
                ),
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("audit record: %s", rec_path)

    # Slack notify.
    try:
        import requests
        webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if webhook:
            requests.post(
                webhook,
                json={
                    "text": (
                        ":fork_and_knife: 都内一人飯3選の伏字を実在店"
                        "9軒に書換完了\n"
                        f"<{URL}|{new_title[:80]}>"
                    ),
                },
                timeout=10,
            )
    except Exception as exc:
        logger.warning("Slack notify failed: %s", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
