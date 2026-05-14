"""One-shot: delete the 2 stale duplicate note URLs that the morning
publish flow left behind. The new URLs (with source-strict content +
ChatGPT images) are kept.

To delete: n8267f93e6aa1 (5 Years $5M old) and n6edffd72b5ad (Cisco old).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("delete_dupes")


URLS_TO_DELETE = [
    "https://note.com/note-user/n/n8267f93e6aa1",
    "https://note.com/note-user/n/n6edffd72b5ad",
]


def main() -> int:
    subprocess.run(
        ["taskkill", "/F", "/IM", "brave.exe"],
        check=False, capture_output=True,
    )
    time.sleep(2)

    from publishers.note_publisher import NotePublisher

    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[str] = []
    try:
        for url in URLS_TO_DELETE:
            logger.info("=" * 70)
            logger.info("Deleting: %s", url)
            try:
                ok = pub.delete_article(url)
            except Exception as exc:  # noqa: BLE001
                logger.exception("delete_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("  OK: %s", url)
            else:
                failed.append(url)
                logger.error("  FAIL: %s", url)
            time.sleep(4)
    finally:
        pub.close()

    logger.info(
        "DONE — deleted=%d failed=%d", succeeded, len(failed),
    )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
