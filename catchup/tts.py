"""Text-to-speech for the catchup digest.

Pipeline: summarized items → gemma4 reading-script (English→katakana,
difficult kanji→hiragana, numbers→spelled out) → edge-tts neural mp3 →
windowless background playback on this PC → old-file cleanup.

Design notes (2026-07-08, user requirements):

* Playback must NOT steal the screen — no media-player window. We spawn
  a hidden PowerShell that drives System.Windows.Media.MediaPlayer and
  exits by itself when the clip ends.
* Disk hygiene: only the newest ``_KEEP_FILES`` mp3s are kept under
  data/audio/.
* Rate defaults to +25% (user: "もう少し速く").
* Everything is free: gemma4 is local, edge-tts needs no API key.

Env toggles:
  CATCHUP_TTS=0        disable entirely (default on)
  CATCHUP_TTS_RATE     e.g. "+25%" (default) / "+40%" / "-10%"
  CATCHUP_TTS_VOICE    default "ja-JP-NanamiNeural" (male: ja-JP-KeitaNeural)
  CATCHUP_TTS_AUTOPLAY=0  generate mp3 but skip local playback
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AUDIO_DIR = _REPO_ROOT / "data" / "audio"
_KEEP_FILES = 3

# gemma4 gets the items in batches this size — small enough to stay
# well inside the context window, large enough to amortise inference.
_SCRIPT_BATCH = 6


def is_enabled() -> bool:
    return os.environ.get("CATCHUP_TTS", "1").strip().lower() not in {
        "", "0", "false", "no", "off",
    }


def _is_autoplay() -> bool:
    return os.environ.get("CATCHUP_TTS_AUTOPLAY", "1").strip().lower() not in {
        "", "0", "false", "no", "off",
    }


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
# 3. Windowless background playback (auto-exits when done)
# ----------------------------------------------------------------------
_PS_PLAY = r"""
Add-Type -AssemblyName PresentationCore
$p = New-Object System.Windows.Media.MediaPlayer
$p.Open([uri]('file:///' + ($args[0] -replace '\\','/')))
$p.Play()
$deadline = (Get-Date).AddSeconds(20)
while (-not $p.NaturalDuration.HasTimeSpan) {
    if ((Get-Date) -gt $deadline) { exit 1 }
    Start-Sleep -Milliseconds 200
}
$dur = $p.NaturalDuration.TimeSpan.TotalSeconds
Start-Sleep -Seconds ([math]::Ceiling($dur) + 1)
$p.Close()
"""


def play_background(path: Path) -> bool:
    """Play *path* with no window; the helper process exits by itself
    right after the clip finishes. Fire-and-forget (does not block)."""
    try:
        subprocess.Popen(
            [
                "powershell", "-NoProfile", "-WindowStyle", "Hidden",
                "-Command", _PS_PLAY, str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        logger.info("tts: background playback started (%s)", path.name)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: playback spawn failed: %s", exc)
        return False


# ----------------------------------------------------------------------
# 4. Disk hygiene
# ----------------------------------------------------------------------
def cleanup_old(keep: int = _KEEP_FILES) -> int:
    """Delete all but the newest *keep* mp3s. Returns count removed."""
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
        if _is_autoplay():
            play_background(mp3)
        cleanup_old()
        return mp3
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: pipeline failed (non-fatal): %s", exc)
        return None


def spawn_detached(items: list[dict]) -> bool:
    """Launch the TTS pass in a DETACHED child process and return
    immediately (~50ms), so catchup's wall-clock time is unaffected.

    2026-07-08 user feedback: the synchronous v1 added 3-5 min to every
    catchup run (gemma4 script batches + synthesis). The child re-runs
    this module via ``py -m catchup.tts <items.json>``; gemma4 inference
    happens inside the child, overlapping with whatever the user does
    next. The tempfile is removed by the child.
    """
    import json
    import sys
    import tempfile

    try:
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="catchup_tts_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, default=str)
        flags = 0
        if os.name == "nt":
            flags = (
                subprocess.CREATE_NO_WINDOW
                | subprocess.DETACHED_PROCESS
            )
        subprocess.Popen(
            [sys.executable, "-m", "catchup.tts", tmp],
            cwd=str(_REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        logger.info("tts: detached worker spawned (%d items)", len(items))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: detach failed (%s) — falling back to sync", exc)
        run_tts(items)
        return False


def _worker_main() -> int:
    """Entry for ``py -m catchup.tts <items.json>`` (detached child)."""
    import json
    import sys

    if len(sys.argv) < 2:
        return 1
    tmp = Path(sys.argv[1])
    try:
        items = json.loads(tmp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    # .env is needed for OLLAMA_API_URL etc. when launched detached.
    env_file = _REPO_ROOT / ".env"
    if env_file.exists():
        for ln in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    logging.basicConfig(level=logging.INFO)
    run_tts(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker_main())
