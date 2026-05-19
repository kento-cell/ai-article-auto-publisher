"""Generate note profile HEADER — 8-bit retro side-scroller style.

User request: a note header in the look of a classic 8-bit / NES-era
side-scrolling platformer (Super-Mario-Bros-style), pop and playful.

Two variants are produced so the user can pick:
  v1_text  — the retro game scene + a pixel-font Japanese tagline.
  v2_scene — the scene only (coins / blocks / pipes tell the story),
             a safe fallback in case the pixel text renders garbled.

IP-safety: the prompt asks for a GENERIC "8-bit retro platformer LOOK"
and explicitly forbids any trademarked character or logo — same
approach the pipeline uses to avoid moderation hits on style names.

Brave must be running in CDP mode (scripts/launch_brave_cdp.bat).
ChatGPT chats are deleted after use per the session-cleanup rule.
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
logger = logging.getLogger("gen_note_header_8bit")

_SCENE = """note クリエイターページ用の横長ワイドなヘッダーバナー画像を1枚、すぐに生成してください。確認や質問は不要です。

【スタイル】
- 8ビット・ファミコン時代のレトロなドット絵（ピクセルアート）。
- 横スクロール型アクションゲームの世界観。ポップで楽しい雰囲気。
- ※重要: 特定の商標・既存ゲームのキャラクターやロゴは一切描かない。
  あくまで汎用的な「8bitレトロゲーム"風"」の表現にとどめる。

【画面の要素（すべてドット絵で）】
- 青空の背景に、白くて四角いドット絵の雲。
- 緑色の階段状の丘、茶色のドット絵の地面。
- レンガ模様のブロック、「？」マーク入りのブロック、緑色の土管。
- 金色のコインが数枚、宙に舞っている（収入・マネタイズの象徴）。
- ブロックが右肩上がりの階段状に積み上がっている（成長・レベルアップの象徴）。

【レイアウト】
- 横長ワイドなバナー構図。
- 画面の左側はやや空けてシンプルに（noteのプロフィールアイコンが左に重なるため）。
{text_block}
【仕上げ】
- くっきりした8bitドット絵。ビビッドでポップな配色。
- 出力は画像1枚のみ。前置き・後置きの文章は不要。"""

_VARIANTS = [
    {
        "name": "v1_text",
        "text_block": (
            "\n【テキスト】\n"
            "- 画面の中央〜右寄りに、8bit風のドット絵フォントで日本語テキスト\n"
            "  「AIを、収入に変える。」を大きく・くっきり・正確に描く。\n"
            "- 誤字脱字なく、はっきり読めること。指定の文字以外は描かない。\n"
        ),
    },
    {
        "name": "v2_scene",
        "text_block": (
            "\n【テキスト】\n"
            "- 文字は入れない。8bitゲーム画面の世界観だけで見せる。\n"
        ),
    },
]


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
    subprocess.run(
        ["cmd", "/c", str(_REPO / "scripts" / "launch_brave_cdp.bat")],
        capture_output=True, timeout=30,
    )
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

    gen = ChatGPTImageGenerator(headless=False)
    results: dict[str, Path | None] = {}
    try:
        gen._open_browser()
        for v in _VARIANTS:
            name = v["name"]
            dest = out_dir / f"note_header_8bit_{name}_{ts}.png"
            logger.info("=" * 60)
            logger.info("generating 8bit header %s", name)
            try:
                gen._start_new_chat()
            except Exception as exc:  # noqa: BLE001
                logger.warning("new chat failed (%s) — continuing", exc)
            prompt = _SCENE.format(text_block=v["text_block"])
            try:
                gen._send_prompt(prompt)
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
