"""Publish the 4 university-student izakaya&cafe note articles.

Each is a ¥100 paid note article — one per university, featuring
individual (non-chain) shops near the campus's nearest station. Bodies
are curated in scripts/_univ_*.md from per-station web research (no
fabricated shops).

ChatGPT cover+inline images via the CDP-attached Brave (Brave does not
need to be closed). Each article is independent: a failure on one is
logged and the loop continues.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
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
logger = logging.getLogger("publish_univ_articles")

PRICE = 100  # ¥100 paid (user-confirmed)

ARTICLES = [
    {
        "aid": "note-univ_seikei_kichijoji",
        "title": "成蹊大生のための、吉祥寺の居酒屋＆カフェ案内",
        "md": "_univ_seikei_kichijoji.md",
        "source": "グルメ / 大学生 / 居酒屋 / カフェ / 吉祥寺",
    },
    {
        "aid": "note-univ_musashi_ekoda",
        "title": "武蔵大生のための、江古田の居酒屋＆カフェ案内",
        "md": "_univ_musashi_ekoda.md",
        "source": "グルメ / 大学生 / 居酒屋 / カフェ / 江古田",
    },
    {
        "aid": "note-univ_tojoshidai_nishiogi",
        "title": "東京女子大生のための、西荻窪の居酒屋＆カフェ案内",
        "md": "_univ_tojoshidai_nishiogi.md",
        "source": "グルメ / 大学生 / 居酒屋 / カフェ / 西荻窪",
    },
    {
        "aid": "note-univ_nodai_kyodo",
        "title": "東京農大生のための、経堂の居酒屋＆カフェ案内",
        "md": "_univ_nodai_kyodo.md",
        "source": "グルメ / 大学生 / 居酒屋 / カフェ / 経堂",
    },
]


def _ensure_cdp_brave() -> None:
    """Make sure a CDP-debug Brave is up; launch via the .bat if not."""
    port = int(os.environ.get("CHATGPT_CDP_PORT", "9222"))

    def _open() -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    if _open():
        logger.info("CDP Brave already up on port %d", port)
        return
    logger.info("CDP Brave not up — running launch_brave_cdp.bat")
    subprocess.run(
        ["cmd", "/c", str(_REPO / "scripts" / "launch_brave_cdp.bat")],
        capture_output=True, timeout=30,
    )
    for _ in range(20):
        if _open():
            logger.info("CDP Brave came up")
            return
        time.sleep(2)
    logger.warning("CDP Brave did not come up — generator may fall back")


def main() -> int:
    _ensure_cdp_brave()

    import main as pipeline

    config = pipeline.load_config()
    articles_dir = _REPO / "data" / "articles"
    results: list[tuple[str, str | None]] = []

    for art in ARTICLES:
        md_path = _REPO / "scripts" / art["md"]
        content = md_path.read_text(encoding="utf-8").strip()
        logger.info("=" * 64)
        logger.info("publishing: %s (%d chars)", art["title"], len(content))
        try:
            url = pipeline._publish_note(
                title=art["title"],
                content=content,
                config=config,
                source=art["source"],
                price=PRICE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("publish raised for %s: %s", art["aid"], exc)
            url = None

        results.append((art["title"], url))
        if not url:
            logger.error("  FAILED: %s", art["aid"])
            continue
        logger.info("  PUBLISHED: %s (¥%d)", url, PRICE)
        record = {
            "title": art["title"],
            "content": content,
            "platform": "note",
            "source": art["source"],
            "article_id": art["aid"],
            "price": PRICE,
            "published_url": url,
            "published_at": datetime.now().isoformat(timespec="seconds"),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "_origin": f"manual univ-student article — scripts/{art['md']}",
        }
        (articles_dir / f"{art['aid']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    logger.info("=" * 64)
    ok = sum(1 for _, u in results if u)
    logger.info("DONE — published=%d / %d", ok, len(ARTICLES))
    for title, url in results:
        logger.info("  %s -> %s", title[:40], url or "FAILED")
    return 0 if ok == len(ARTICLES) else 2


if __name__ == "__main__":
    raise SystemExit(main())
