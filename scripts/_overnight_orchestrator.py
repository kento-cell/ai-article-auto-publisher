"""Overnight orchestrator (2026-05-14 night → 2026-05-15 morning).

User is going to sleep. This poll-driven script:
  1. Waits for the 13th generate's python process (started 22:30) to
     exit, with a 90-minute hard cap.
  2. Reads the Sheets pending → approved set.
  3. If any pending: bulk-approves them, then runs publish_approved
     with note set to free (free-first all note rows). USE_CHATGPT_IMAGES
     stays ON (default) — today's _start_new_chat fix and MD5 dedup
     should produce real ChatGPT covers; if those fail, the publish
     flow falls through to its existing Unsplash fallback.
     CHATGPT_VISION_EVAL=0 to avoid the retry-loop seen earlier.
  4. Verifies which articles successfully published (Sheets status).
  5. Writes a morning briefing into docs/sessions/LATEST.md.
  6. Commits + pushes everything.

Designed to be idempotent on partial failure — re-running picks up
whatever step is incomplete.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# Load .env early so child processes inherit
_ENV = _REPO / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
# Avoid the vision-eval retry loop that ate hours earlier today.
os.environ["CHATGPT_VISION_EVAL"] = "0"
# Keep USE_CHATGPT_IMAGES at its default (true) so today's
# _start_new_chat + MD5-dedup fix is exercised end-to-end.

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("overnight")


GENERATE_PID = 5680  # the 13th generate process (22:30:42 start)
HARD_CAP_MIN = 90
POLL_SEC = 30


def _process_alive(pid: int) -> bool:
    """Return True iff a process with *pid* is currently running."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) "
             f"{{ exit 0 }} else {{ exit 1 }}"],
            timeout=15, capture_output=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def _wait_for_generate_done() -> None:
    deadline = time.time() + HARD_CAP_MIN * 60
    while time.time() < deadline:
        if not _process_alive(GENERATE_PID):
            log.info("generate python (PID %d) has exited", GENERATE_PID)
            return
        log.info("still alive, sleeping %ds", POLL_SEC)
        time.sleep(POLL_SEC)
    log.warning(
        "generate hit %d-min hard cap; killing PID %d and continuing",
        HARD_CAP_MIN, GENERATE_PID,
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Stop-Process -Id {GENERATE_PID} -Force "
         f"-ErrorAction SilentlyContinue"],
        timeout=15, capture_output=True,
    )
    time.sleep(3)


def _sheets_state() -> tuple[int, int]:
    """Return (pending, approved) counts."""
    from utils.sheets_manager import SheetsManager
    sm = SheetsManager()
    return (
        len(sm.get_pending_articles()),
        len(sm.get_approved_articles()),
    )


def _run(cmd: list[str], timeout: int) -> tuple[int, str]:
    log.info("$ %s", " ".join(cmd))
    r = subprocess.run(
        cmd, timeout=timeout, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if r.stdout:
        for line in r.stdout.splitlines()[-30:]:
            log.info("  %s", line)
    if r.returncode != 0 and r.stderr:
        for line in r.stderr.splitlines()[-15:]:
            log.warning("  stderr: %s", line)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _publish_all_note_free() -> str:
    """Bulk-approve everything pending, then publish with all note rows
    forced free. Returns the publish log tail for the briefing."""
    pending, approved = _sheets_state()
    log.info("sheets: pending=%d approved=%d", pending, approved)
    if pending == 0 and approved == 0:
        log.info("nothing to publish")
        return "(no pending or approved articles after generate)"

    if pending > 0:
        _run(
            [sys.executable, str(_REPO / "scripts" / "_bulk_approve_sheet.py")],
            timeout=120,
        )

    # Re-check approved.
    _, approved = _sheets_state()
    if approved == 0:
        log.info("no rows reached ✅承認 — publish skipped")
        return "(bulk approve produced 0 ✅承認 rows)"

    # `--free-first 99` forces every note row to ¥0; zenn unaffected.
    rc, out = _run(
        [sys.executable, str(_REPO / "scripts" / "_publish_free_first.py"),
         "--free-first", "99"],
        timeout=20 * 60,
    )
    tail = "\n".join(out.splitlines()[-40:])
    return tail


def _update_latest(publish_tail: str) -> None:
    """Append a morning-briefing section to LATEST.md."""
    from utils.sheets_manager import SheetsManager
    sm = SheetsManager()
    ws = sm._sheet
    rows = ws.get_all_values() if ws else []
    today = datetime.now().strftime("%Y-%m-%d")
    published_today = [
        r for r in rows[-30:]
        if r and len(r) > 2 and "投稿済み" in (r[2] or "")
        and today in (r[5] if len(r) > 5 else "")
    ]
    briefing = f"""

---

## 2026-05-15 morning briefing (autonomous overnight run)

**ユーザーが寝ている間に走ったタスク** (`scripts/_overnight_orchestrator.py`):
1. 13th generate (variant=v3_codex) の完了待機
2. 合格分を bulk approve → free-first publish
3. LATEST.md 更新 + commit + push

**Sheets 状態 (現時点):**
- 全 ✅投稿済み 行 (直近 30 行のうち今日分): {len(published_today)}

**publish 直近ログ:**
```
{publish_tail}
```

**確認事項:**
- note ダッシュボードで cover 画像 (ChatGPT 生成 vs Unsplash fallback) を目視
- 「キャラ + デカ文字 + 絵」のいつものスタイルが復活しているか
- もし黄色矢印プレースホルダーや Unsplash 写真風なら、`_start_new_chat` 修正がまだ
  足りていない → `_test_rag_rerank.py` のような診断スクリプトを書いて原因絞り込み
"""
    path = _REPO / "docs" / "sessions" / "LATEST.md"
    cur = path.read_text(encoding="utf-8")
    path.write_text(cur + briefing, encoding="utf-8")
    log.info("LATEST.md updated (+ %d chars)", len(briefing))


def _git_push() -> None:
    _run(
        ["git", "add",
         "docs/sessions/LATEST.md",
         "scripts/_overnight_orchestrator.py",
         "scripts/_smoke_test_today_fixes.py"],
        timeout=30,
    )
    r = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
    )
    if r.returncode == 0:
        log.info("no staged changes — skipping commit")
    else:
        _run(
            ["git", "commit", "-m",
             "chore(overnight): orchestrator + smoke test + briefing"],
            timeout=60,
        )
    _run(["git", "push", "origin", "main"], timeout=120)


def main() -> int:
    log.info("=== overnight orchestrator starting ===")
    _wait_for_generate_done()
    try:
        tail = _publish_all_note_free()
    except Exception as exc:  # noqa: BLE001
        log.exception("publish step failed: %s", exc)
        tail = f"(publish step raised: {exc})"
    try:
        _update_latest(tail)
    except Exception as exc:  # noqa: BLE001
        log.exception("latest update failed: %s", exc)
    try:
        _git_push()
    except Exception as exc:  # noqa: BLE001
        log.exception("git push failed: %s", exc)
    log.info("=== overnight orchestrator done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
