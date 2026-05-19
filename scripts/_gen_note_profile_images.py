"""Generate note profile images (icon + header) via the ChatGPT pipeline.

One-off: builds a character-avatar icon (square) and a profile header
banner (landscape) for the note account, positioned as an "AI x 実務 x
マネタイズ" creator.

Uses the clean ``is_cover=False`` prompt path (no clickbait text
overlay — that path is for article thumbnails) and deletes each
ChatGPT chat after use per the session-cleanup rule.

Brave must be running in CDP mode (scripts/launch_brave_cdp.bat); the
generator attaches via CHATGPT_CDP_PORT. This script ensures a CDP
Brave is up before generating.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
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
logger = logging.getLogger("gen_note_profile")

_STYLE = (
    "モダンでクリーンなアニメ・イラスト調。\n"
    "- 親しみやすく洗練されたキャラクターイラスト\n"
    "- すっきりした線、上品でフラットな配色"
    "（ディープブルー〜パープル〜ティールのテック系パレット＋温かいアクセント光）\n"
    "- 知的でプロフェッショナル、かつ親近感のある雰囲気\n"
    "- テキスト・読める文字・ロゴ・透かし・UIは一切描かない\n"
    "- 背景はシンプルに保つ"
)

_ICON_PROMPT = (
    "AIを実務と収入に変えるコンテンツクリエイターのキャラクターアイコン。\n"
    "被写体: 20〜30代の日本人男性キャラクター。知的で親しみやすく、"
    "自信のある穏やかな表情（軽い微笑み）。スマートカジュアルな服装"
    "（シンプルなシャツか軽いジャケット）。\n"
    "構図: 顔を中央に置いたバストアップ。正面〜やや斜め、視線はこちら。"
    "丸く切り抜いても顔がはっきり見えるよう、顔を大きめに中央配置。\n"
    "背景: シンプルな単色〜ソフトグラデーション（ディープブルー〜パープル系）。"
    "ごく控えめに抽象的なデータや光のモチーフをぼかして添える程度。\n"
    "全体: クリーンで洗練。小さく表示しても視認性が高いこと。"
)

_HEADER_PROMPT = (
    "note プロフィール用の横長ヘッダーバナー。\n"
    "テーマ: 「AIを実務と収入に変える」を視覚的に表現。\n"
    "被写体: アイコンと同一人物の日本人男性キャラクターを画面の右寄りに配置し、"
    "ノートPCで作業している様子。前向きで集中した表情。\n"
    "要素: 背景に抽象的なAIの光・データのフロー・右肩上がりの成長の象徴を"
    "やわらかく散らす（実務と成果のイメージ）。\n"
    "構図: 画面左3分の1は静かでシンプルに保つ"
    "（note のプロフィールアイコンと名前が左に重なるため）。見せ場は中央〜右。\n"
    "配色: ディープブルー〜パープル〜ティールのテック系パレット＋温かいアクセント光。\n"
    "全体: クリーンでモダン、洗練。"
)


def _ensure_cdp_brave() -> None:
    """Make sure a CDP-debug Brave is up; launch via the .bat if not."""
    port = int(os.environ.get("CHATGPT_CDP_PORT", "9222"))

    def _port_open() -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    if _port_open():
        logger.info("CDP Brave already up on port %d", port)
        return
    logger.info("CDP Brave not up — running launch_brave_cdp.bat")
    bat = _REPO / "scripts" / "launch_brave_cdp.bat"
    subprocess.run(["cmd", "/c", str(bat)], capture_output=True, timeout=30)
    for _ in range(20):
        if _port_open():
            logger.info("CDP Brave came up")
            return
        time.sleep(2)
    logger.warning("CDP Brave did not come up — generator may fall back")


def main() -> int:
    _ensure_cdp_brave()
    from generators.chatgpt_image_generator import ChatGPTImageGenerator

    out_dir = _REPO / "data" / "images" / "profile"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    jobs = [
        ("icon", "square", _ICON_PROMPT, out_dir / f"note_icon_{ts}.png"),
        ("header", "landscape", _HEADER_PROMPT, out_dir / f"note_header_{ts}.png"),
    ]

    gen = ChatGPTImageGenerator(headless=False)
    results: dict[str, Path | None] = {}
    try:
        gen._open_browser()
        for name, size, prompt, dest in jobs:
            logger.info("=" * 60)
            logger.info("generating %s (%s)", name, size)
            try:
                gen._start_new_chat()
            except Exception as exc:  # noqa: BLE001
                logger.warning("new chat failed (%s) — continuing", exc)
            full = gen._build_prompt(
                prompt, size, is_cover=False, style_block=_STYLE,
            )
            try:
                gen._send_prompt(full)
                url = gen._wait_for_image(skip_urls=set())
                if url:
                    gen._download_via_browser(url, dest)
                    results[name] = dest
                    logger.info("  %s OK -> %s", name, dest)
                else:
                    results[name] = None
                    logger.error("  %s: no image found", name)
            except Exception as exc:  # noqa: BLE001
                logger.exception("  %s failed: %s", name, exc)
                results[name] = None
            finally:
                # Session-cleanup rule: delete the chat after use.
                try:
                    gen._delete_current_chat()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("delete chat failed: %s", exc)
            time.sleep(3)
    finally:
        gen._close_browser()

    print("RESULTS:")
    for name, p in results.items():
        print(f"  {name}: {p}")
    return 0 if all(results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
