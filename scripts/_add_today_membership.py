"""One-shot: add 2026-06-01's published note articles to the membership
benefit list (selection-mode flow), then VERIFY by reloading
/{handle}/membership/notes and checking each slug now appears.
"""
from __future__ import annotations

import logging
import os
import sys
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("add_today_membership")

HANDLE = os.environ.get("NOTE_HANDLE", "")  # set in .env; no hardcoded handle
TARGETS = {
    "nb8a49e7d42e5": "116 緊急ケア (有料)",
    "n927503f7e3a4": "117 シカ (有料)",
    "n9d12f8cb9155": "113 リジュラン (free)",
    "n762c35e158ec": "112 K-food (free)",
}


def main() -> int:
    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    pub._ensure_started()
    page = pub._page
    try:
        pub._assert_logged_in()
        logger.info("login OK; adding %d articles to membership", len(TARGETS))
        res = pub.add_articles_to_membership(list(TARGETS.keys()))
        for s, label in TARGETS.items():
            logger.info("  add %s -> %s  (%s)", s, "OK" if res.get(s) else "FAIL", label)

        # Verify against the live membership article list.
        logger.info("verifying via /%s/membership/notes ...", HANDLE)
        present = set()
        try:
            page.goto(
                f"https://note.com/{HANDLE}/membership/notes",
                wait_until="domcontentloaded", timeout=30_000,
            )
            page.wait_for_timeout(3_000)
            # paginate a little in case of "もっとみる"
            for _ in range(3):
                try:
                    more = page.locator("button:has-text('もっとみる')").first
                    if more.count() and more.is_visible(timeout=800):
                        more.click(timeout=2000)
                        page.wait_for_timeout(1500)
                    else:
                        break
                except Exception:
                    break
            hrefs = page.evaluate(
                """() => Array.from(document.querySelectorAll("a[href*='/n/']"))
                    .map(a => a.getAttribute('href')||'')"""
            ) or []
            for s in TARGETS:
                if any(s in h for h in hrefs):
                    present.add(s)
        except Exception as exc:
            logger.warning("verification nav failed: %s", exc)

        logger.info("=== VERIFICATION (membership/notes) ===")
        for s, label in TARGETS.items():
            logger.info("  %s -> %s  (%s)", s, "PRESENT" if s in present else "MISSING", label)
        logger.info("DONE — verified %d/%d present", len(present), len(TARGETS))
        return 0 if len(present) == len(TARGETS) else 1
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
