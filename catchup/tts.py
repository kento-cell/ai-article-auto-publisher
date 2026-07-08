"""Text-to-speech for the catchup digest.

Pipeline: summarized items -> gemma4 reading-script (English->katakana,
difficult kanji->hiragana, numbers->spelled out) -> edge-tts neural mp3
-> desktop shortcut the user double-clicks whenever they want to listen.

Design history (2026-07-08):

* v1: windowless background auto-play right after generation. User
  reported it never actually reached their ears in practice (easy to
  miss a silent playback that starts on its own).
* v2: dropped autoplay, added Slack upload instead. Blocked on the
  bot needing a channel invite (`not_in_channel`), and user decided
  Slack can't "read aloud" anyway (Slack has no auto-play — a user
  still has to tap play manually, same friction as just double-
  clicking a local file).
* v3: desktop shortcut ("AIキャッチアップを聞く.lnk") the user
  double-clicks whenever convenient. Still ran gemma4+edge-tts
  AUTOMATICALLY at the end of every catchup run, regardless of
  whether the user actually intended to listen that day.
* v4 (this revision, per user 2026-07-08 explicit request — "毎回
  自動で回るのはもったいない"): voice generation is now OPT-IN.
  ``runner.py`` no longer calls into this module at all; it only
  stashes the delivered item list via :func:`stash_last_delivered`.
  The user runs ``py -m catchup.tts --last`` (or double-clicks
  ``run_catchup_voice.bat``) only on the days they actually want to
  listen — gemma4/edge-tts never run unless a human asked for it.

Env toggles:
  CATCHUP_TTS_RATE     e.g. "+25%" (default) / "+40%" / "-10%"
  CATCHUP_TTS_VOICE    default "ja-JP-NanamiNeural" (male: ja-JP-KeitaNeural)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AUDIO_DIR = _REPO_ROOT / "data" / "audio"
_KEEP_FILES = 3
_SHORTCUT_NAME = "AIキャッチアップを聞く.lnk"
_LAST_DELIVERED_PATH = _AUDIO_DIR / "last_delivered.json"

# gemma4 gets the items in batches this size — small enough to stay
# well inside the context window, large enough to amortise inference.
_SCRIPT_BATCH = 6


def stash_last_delivered(items: list[dict]) -> None:
    """Save exactly what the most recent catchup run posted to Slack,
    so a later opt-in voice pass doesn't need to re-fetch/re-summarise
    anything. Overwrites — only the latest run is kept. Non-fatal."""
    try:
        _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        _LAST_DELIVERED_PATH.write_text(
            json.dumps(items, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        logger.info("tts: stashed %d delivered items for opt-in voice", len(items))
    except OSError as exc:
        logger.warning("tts: stash failed (non-fatal): %s", exc)


def load_last_delivered() -> list[dict] | None:
    """Load the items stashed by the most recent catchup run, or None
    if none exists yet."""
    if not _LAST_DELIVERED_PATH.exists():
        return None
    try:
        return json.loads(_LAST_DELIVERED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ----------------------------------------------------------------------
# 1. Reading script via gemma4
# ----------------------------------------------------------------------
_SCRIPT_PROMPT = """以下の AI ニュース要約を、日本語の音声読み上げ用台本に変換してください。

ルール:
- 英語の固有名詞・略語・製品名はカタカナに変換する
  (例: Anthropic→アンソロピック、Claude→クロード、LLM→エルエルエム、GitHub→ギットハブ)
- 読み間違えやすい漢字はひらがなに開く
- 数値は読み仮名にする (例: 3.4倍→さんてんよんばい、27%→にじゅうななパーセント)
- URL・記号・箇条書き記号は除去し、自然な話し言葉の文章にする
- 各ニュースの間に「次のニュースです。」を挟む
- 台本の本文のみを出力する。前置き・後置き・見出しは不要

ニュース要約:
{items}"""


def build_script(items: list[dict]) -> str:
    """Convert summarized catchup items into one TTS-safe script."""
    from generators.llm_config import get_llm

    llm = get_llm("summarizer")
    parts: list[str] = []
    for i in range(0, len(items), _SCRIPT_BATCH):
        batch = items[i : i + _SCRIPT_BATCH]
        lines = []
        for it in batch:
            summary = (it.get("jp_summary") or it.get("title") or "").strip()
            if summary:
                lines.append(f"- {it.get('title', '')}: {summary}")
        if not lines:
            continue
        try:
            out = llm.generate(
                _SCRIPT_PROMPT.format(items="\n".join(lines)),
                temperature=0.2,
            ).strip()
            if out:
                parts.append(out)
        except Exception as exc:  # noqa: BLE001 — a lost batch is acceptable
            logger.warning("tts: script batch %d failed: %s", i // _SCRIPT_BATCH, exc)
    header = "エーアイ、キャッチアップです。本日のニュースをお伝えします。"
    footer = "以上、本日のキャッチアップでした。"
    return "\n".join([header, *parts, footer])


# ----------------------------------------------------------------------
# 2. Synthesis via edge-tts
# ----------------------------------------------------------------------
def synthesize(script: str) -> Path | None:
    """Render *script* to an mp3 under data/audio/. Returns path or None."""
    import edge_tts

    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    dest = _AUDIO_DIR / f"catchup_{time.strftime('%Y%m%d_%H%M%S')}.mp3"
    voice = os.environ.get("CATCHUP_TTS_VOICE", "ja-JP-NanamiNeural").strip()
    rate = os.environ.get("CATCHUP_TTS_RATE", "+25%").strip()

    async def _run() -> None:
        tts = edge_tts.Communicate(script, voice=voice, rate=rate)
        await tts.save(str(dest))

    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: synthesis failed: %s", exc)
        return None
    if not dest.exists() or dest.stat().st_size < 10_000:
        logger.warning("tts: output missing/too small")
        return None
    logger.info("tts: %d bytes -> %s (voice=%s rate=%s)",
                dest.stat().st_size, dest.name, voice, rate)
    return dest


# ----------------------------------------------------------------------
# 3. Desktop shortcut — the ONE thing the user interacts with.
# ----------------------------------------------------------------------
def _desktop_dir() -> Path:
    # OneDrive can relocate the Desktop folder; USERPROFILE\Desktop is
    # correct on this machine (checked against existing paths in repo
    # docs) but fall back gracefully if it doesn't exist.
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "デスクトップ",
        Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Desktop",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def refresh_desktop_shortcut(mp3: Path) -> Path | None:
    """(Re)point the single desktop shortcut at *mp3*.

    Windows-only (uses WScript.Shell COM via PowerShell — no extra
    pip dependency). Overwrites the same .lnk every run so there is
    always exactly one icon, never a pile of shortcuts.
    """
    if os.name != "nt":
        logger.info("tts: desktop shortcut skipped (non-Windows)")
        return None
    desktop = _desktop_dir()
    if not desktop.is_dir():
        logger.warning("tts: desktop dir not found — skipping shortcut")
        return None
    link_path = desktop / _SHORTCUT_NAME
    ps = (
        "$W = New-Object -ComObject WScript.Shell; "
        f"$S = $W.CreateShortcut('{link_path}'); "
        f"$S.TargetPath = '{mp3}'; "
        f"$S.Description = 'AIキャッチアップ 音声版 (聴き終わったら削除してOK)'; "
        "$S.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            check=True, capture_output=True, timeout=15,
        )
        logger.info("tts: desktop shortcut refreshed -> %s", link_path)
        return link_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: shortcut creation failed: %s", exc)
        return None


# ----------------------------------------------------------------------
# 4. Disk hygiene — prune OLD generations only, never the current one.
# ----------------------------------------------------------------------
def cleanup_old(keep: int = _KEEP_FILES) -> int:
    """Delete all but the newest *keep* mp3s. Returns count removed.

    The newest file (the one the desktop shortcut points at) is always
    inside the keep window, so this never removes what the user is
    about to listen to. Deleting the CURRENT file is the user's call
    (delete it themselves from the desktop / data/audio after
    listening) — never automatic, per explicit user request.
    """
    if not _AUDIO_DIR.exists():
        return 0
    files = sorted(
        _AUDIO_DIR.glob("catchup_*.mp3"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in files[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    if removed:
        logger.info("tts: cleaned up %d old mp3(s)", removed)
    return removed


# ----------------------------------------------------------------------
# Orchestrator (called from runner)
# ----------------------------------------------------------------------
def run_tts(items: list[dict]) -> Path | None:
    """Full TTS pass. Never raises — catchup must not fail because of
    audio. Returns the mp3 path when synthesis succeeded."""
    try:
        script = build_script(items)
        if len(script) < 100:
            logger.warning("tts: script too short — skipping")
            return None
        mp3 = synthesize(script)
        if mp3 is None:
            return None
        refresh_desktop_shortcut(mp3)
        cleanup_old()
        return mp3
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: pipeline failed (non-fatal): %s", exc)
        return None


def spawn_detached_for_last() -> bool:
    """Launch an opt-in voice pass over the most recently delivered
    catchup, in a DETACHED child process (returns in ~50ms instead of
    blocking the terminal for the ~1-2 min gemma4+edge-tts takes).

    This is the function ``run_catchup_voice.bat`` calls. It does
    nothing (and spends nothing) unless the user explicitly runs it.
    """
    if load_last_delivered() is None:
        logger.warning("tts: no stashed catchup run to voice — run catchup first")
        return False
    try:
        flags = 0
        if os.name == "nt":
            flags = (
                subprocess.CREATE_NO_WINDOW
                | subprocess.DETACHED_PROCESS
            )
        subprocess.Popen(
            [__import__("sys").executable, "-m", "catchup.tts", "--last"],
            cwd=str(_REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        logger.info("tts: detached worker spawned for last-delivered digest")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: detach failed (%s) — falling back to sync", exc)
        items = load_last_delivered()
        if items:
            run_tts(items)
        return False


def _worker_main() -> int:
    """CLI entry point.

    ``py -m catchup.tts --last``  — opt-in: voice the most recently
        delivered catchup run (stashed by runner.py). This is the only
        supported mode now — gemma4/edge-tts run ONLY when a human
        explicitly asks, never automatically after a catchup run.
    """
    import sys

    if "--last" not in sys.argv:
        print("Usage: py -m catchup.tts --last", file=sys.stderr)
        return 1

    # .env is needed for OLLAMA_API_URL etc. when launched detached.
    env_file = _REPO_ROOT / ".env"
    if env_file.exists():
        for ln in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    # spawn_detached_for_last() redirects this process's stdout/stderr
    # to DEVNULL, so basicConfig(stream=stdout) would be silent — log
    # to a file instead so the run is inspectable after the fact.
    log_dir = _REPO_ROOT / "data" / "audio"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        filename=str(log_dir / "tts_worker.log"),
        filemode="a",
        format="%(asctime)s %(levelname)s %(message)s",
    )

    items = load_last_delivered()
    if not items:
        logger.warning("tts: no stashed catchup run found — run catchup first")
        return 1
    logger.info("tts worker started (%d items, opt-in --last)", len(items))
    mp3 = run_tts(items)
    logger.info("tts worker finished (mp3=%s)", mp3)
    return 0 if mp3 else 1


if __name__ == "__main__":
    raise SystemExit(_worker_main())
