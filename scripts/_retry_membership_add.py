"""Retry `_add_to_memberships_via_dashboard` for note posts whose
post-publish membership-add step failed.

KNOWN LIMITATION (2026-05-13): even when starting from the home page,
the helper hits "クリエーターページ リンクが見つからない" and
"「メンバー特典記事を追加する」 ボタンが見つかりません" — the avatar
dropdown selectors are stale or the menu open/close race trips the
visibility check. Because the helper silent-returns on each failure
(no exception), this wrapper reports ok=4 even though zero rows were
flipped. Until the underlying selectors are fixed:
  1. Use this script as a starting harness for live DOM inspection
     (run headed, breakpoint in `_add_to_memberships_via_dashboard`).
  2. Or do the add manually via the note dashboard.

Strategy when fixed: start fresh from the note home page so the
avatar menu has its normal structure, then call the existing private
helper for each URL.
"""
from __future__ import annotations

import logging
import os
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
logger = logging.getLogger("retry_membership")

TARGETS = [
    "https://note.com/note-user/n/nebdb6edacb1e",  # Louis Rossmann
    "https://note.com/note-user/n/n5a0a2ad50965",  # Cannot stainless steel
    "https://note.com/note-user/n/n536e614dc601",  # Suno / Udio
    "https://note.com/note-user/n/nd5812c715125",  # Reddit
]


def main() -> int:
    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    pub._ensure_started()
    assert pub._page is not None
    succeeded = 0
    failed: list[str] = []
    try:
        pub._assert_logged_in()
        # Land on the home page so the avatar menu and dashboard
        # navigation behave like a normal user session — the
        # post-publish editor page is a different state and that's
        # why the original add step failed.
        pub._page.goto("https://note.com/", wait_until="domcontentloaded")
        pub._page.wait_for_timeout(2_000)
        for url in TARGETS:
            slug = url.rstrip("/").split("/")[-1]
            logger.info("=" * 60)
            logger.info("processing slug=%s", slug)
            try:
                pub._add_to_memberships_via_dashboard(url)
                succeeded += 1
                logger.info("OK: %s", slug)
            except Exception as exc:  # noqa: BLE001
                logger.exception("FAIL: %s — %s", slug, exc)
                failed.append(slug)
            # Reset to home for next iteration so each URL starts
            # from a known state.
            try:
                pub._page.goto("https://note.com/", wait_until="domcontentloaded")
                pub._page.wait_for_timeout(2_000)
            except Exception:
                pass
            time.sleep(2)
    finally:
        pub.close()
    logger.info("DONE — ok=%d, fail=%d (%s)", succeeded, len(failed), failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
