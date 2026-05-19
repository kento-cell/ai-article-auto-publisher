"""Force-publish the two most recent Zenn drafts as full articles.

Normally ``main.py --publish`` routes Zenn posts with score < 82.5 to
Zenn Scraps. The user explicitly wants these two posted as real
articles regardless of score, so we bypass the threshold gate and
call :func:`main._publish_zenn` directly.

Targets are pinned by article JSON filename to avoid any ambiguity
with future drafts:

    data/articles/zenn-Claude_Mythosはパンドラの箱.json
    data/articles/zenn-翻訳記事_AIコーディングツールによって.json

Pre-flight checks (Mermaid lint, URL sanity, placeholder scan) are
performed before touching the Zenn repo. After a successful publish
the Sheets row status is moved to "✅投稿済み" and a Slack
notification is emitted, matching the normal publish path.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load .env before importing modules that read env at import time.
for _line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

import main  # noqa: E402
from publishers.slack_notifier import SlackNotifier  # noqa: E402
from utils.sheets_manager import SheetsManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("publish_latest_zenn")

_MMDC = os.path.expandvars(r"%APPDATA%\npm\mmdc.cmd")

TARGETS: list[str] = [
    "data/articles/zenn-Claude_Mythosはパンドラの箱.json",
    "data/articles/zenn-翻訳記事_AIコーディングツールによって.json",
]


def _lint_mermaid(content: str, label: str) -> list[str]:
    """Return a list of Mermaid lint errors for every fenced mermaid block."""
    errs: list[str] = []
    blocks = re.findall(r"```mermaid\n(.*?)\n```", content, re.DOTALL)
    if not blocks:
        return errs
    if not Path(_MMDC).exists():
        logger.warning("mmdc not found at %s — skipping lint", _MMDC)
        return errs
    for idx, block in enumerate(blocks, start=1):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mmd", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(block)
            mmd = tf.name
        svg = mmd.replace(".mmd", ".svg")
        try:
            r = subprocess.run(
                [_MMDC, "-i", mmd, "-o", svg],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if r.returncode != 0:
                errs.append(
                    f"{label} block {idx}: mmdc exit {r.returncode} — {(r.stderr or '').strip()[:200]}"
                )
            elif not Path(svg).exists() or Path(svg).stat().st_size == 0:
                errs.append(f"{label} block {idx}: empty svg output")
            else:
                logger.info("  mermaid block %d ok (%d bytes)", idx, Path(svg).stat().st_size)
        except Exception as exc:
            errs.append(f"{label} block {idx}: {exc}")
        finally:
            try:
                Path(mmd).unlink(missing_ok=True)
                Path(svg).unlink(missing_ok=True)
            except Exception:
                pass
    return errs


def _scan_placeholders(content: str) -> list[str]:
    """Flag obvious unfinished text like '検索して追記'."""
    hits: list[str] = []
    bad_markers = [
        "検索して追記",
        "あとで埋める",
        "後で追記",
        "TODO:追加",
        "(Anthropicの論文を検索",
    ]
    for m in bad_markers:
        if m in content:
            hits.append(m)
    # Verbose duplicate anchors: [https://...](https://...)
    for m in re.finditer(
        r"\[([^\]]+)\]\(((?:[^()]|\([^)]*\))+)\)", content
    ):
        label = m.group(1).strip()
        url = m.group(2).strip()
        if label == url or re.fullmatch(r"https?://\S+", label):
            hits.append(f"verbose anchor: {url[:80]}")
    return hits


def main_cli() -> int:
    sheets = SheetsManager()
    slack = SlackNotifier()

    failures: list[str] = []
    for rel in TARGETS:
        path = _REPO / rel
        if not path.exists():
            logger.error("missing JSON: %s", rel)
            failures.append(rel)
            continue
        stored = json.loads(path.read_text(encoding="utf-8"))
        title = stored["title"]
        content = stored["content"]
        article_id = stored.get("article_id", path.stem)

        logger.info("== %s ==", title[:60])

        # Pre-flight: Mermaid lint + placeholder scan
        mermaid_errs = _lint_mermaid(content, label=title[:30])
        placeholder_errs = _scan_placeholders(content)
        issues = mermaid_errs + placeholder_errs
        if issues:
            logger.error("pre-flight issues — aborting publish:")
            for e in issues:
                logger.error("  - %s", e)
            failures.append(article_id)
            continue
        logger.info("pre-flight passed (mermaid %d, placeholder 0)", len(mermaid_errs))

        try:
            url = main._publish_zenn(article_id, title, content, stored)
        except Exception as exc:
            logger.exception("publish crash: %s", exc)
            failures.append(article_id)
            continue

        if not url:
            logger.error("publish returned empty url")
            failures.append(article_id)
            continue

        logger.info("[OK] %s", url)
        # Update sheet status + notify
        try:
            sheets.update_status(article_id, "✅投稿済み")
        except Exception as exc:
            logger.warning("sheet update failed: %s", exc)
        try:
            slack.notify_published("zenn", title, url)
        except Exception as exc:
            logger.warning("slack notify failed: %s", exc)

    if failures:
        logger.error("failures: %s", failures)
        return 1
    logger.info("All target posts published successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
