"""Generate note profile HEADER variants — typography-driven, pop style.

The first header (a character illustration) was rejected as too plain.
This produces 3 typography-forward, note-thumbnail-style header banners
(text is the hero, pop palette) so the user can pick one.

Custom prompts request exact Japanese text and bypass
ChatGPTImageGenerator._build_prompt — its is_cover=False path forbids
text, and its is_cover=True path adds article-clickbait framing.

Brave must be running in CDP mode (scripts/launch_brave_cdp.bat); the
generator attaches via CHATGPT_CDP_PORT. ChatGPT chats are deleted
after use per the session-cleanup rule.
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
logger = logging.getLogger("gen_note_header")

_FRAME = """note クリエイターページ用の横長ワイドなヘッダーバナー画像を1枚、すぐに生成してください。確認や質問は不要です。

【デザイン方針】
- タイポグラフィ主体。文字が主役のポップなバナー。
- note / SNS のサムネイル風。目を引くが、ゴチャゴチャさせない。
- 横長ワイド（おおよそ16:9〜2:1）。

【画像内に大きく・正確に描く日本語テキスト】
  「{tagline}」
- 極太ゴシック体、力強くポップに。
- {color}
- 文字に縁取りと軽いドロップシャドウをつけ、くっきり読めるように。
- 誤字脱字なく正確に描く。指定したテキスト以外の文字は描かない。

【レイアウト】
- 文字は画面の中央〜右寄りに大きく配置。
- 画面の左側はやや余白・シンプルに保つ（noteのプロフィールアイコンが左に重なるため）。
- 装飾は控えめに（{deco}）。文字の可読性を最優先。

【スタイル】
- {mood}
- イラストやキャラクターは描かない。文字とシンプルな図形・装飾のみ。

出力は画像1枚のみ。前置き・後置きの文章は不要。"""

_VARIANTS = [
    {
        "name": "v1_navy",
        "tagline": "AIを、収入に変える。",
        "color": "ディープネイビーの背景に、白とゴールドの極太文字。",
        "deco": "細い直線と小さなドットをほんの少しだけ",
        "mood": "信頼感のあるシャープなポップ。知的さとポップさを両立。",
    },
    {
        "name": "v2_gradient",
        "tagline": "AI × 実務 × マネタイズ",
        "color": "ブルーからパープル、ピンクへの明るいグラデーション背景に、白の極太文字。",
        "deco": "きらめきや小さな幾何学図形を軽く散らす",
        "mood": "明るく軽快なポップ。3語を「×」で並べたリズム感を出す。",
    },
    {
        "name": "v3_vivid",
        "tagline": "AI実務の、リアル。",
        "color": "ビビッドなティールの単色背景に、白と黒の強コントラスト文字。",
        "deco": "吹き出し・矢印・ドットを少し添える",
        "mood": "一番ポップで元気。雑誌の見出しのような勢い。",
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
            dest = out_dir / f"note_header_{name}_{ts}.png"
            logger.info("=" * 60)
            logger.info("generating header %s — %r", name, v["tagline"])
            try:
                gen._start_new_chat()
            except Exception as exc:  # noqa: BLE001
                logger.warning("new chat failed (%s) — continuing", exc)
            prompt = _FRAME.format(**v)
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
