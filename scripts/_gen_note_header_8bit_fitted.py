"""Generate an 8-bit note header FITTED to note's header crop.

note's creator-page header displays only the CENTER horizontal band of
the uploaded image (~a 5.9:1 strip; the help center calls it "center
1280x216"). The earlier 8-bit header put its text in the upper area,
so note cropped the top/bottom off the text ("見切れ").

Fix, in two steps:
  1. Generate an 8-bit header composed with the text + key elements in
     the VERTICAL CENTER, sky above / ground below as safe crop bleed.
  2. PIL-fit the result to note's recommended 1920x1006 so the centered
     content lands inside note's visible band.

Brave must be running in CDP mode (scripts/launch_brave_cdp.bat).
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
logger = logging.getLogger("gen_note_header_8bit_fitted")

_PROMPT = """note クリエイターページ用のヘッダーバナー画像を1枚、すぐに生成してください。確認や質問は不要です。

【最重要・レイアウト制約】
noteのヘッダーは「画像の縦中央の横帯」だけが表示され、上下は大きく切り取られます。
そのため、見せたい要素はすべて画像の"縦の中央"に集めてください。
- テキストと、8bitの地面・ブロック・コインなどの主要素は、すべて画面の縦中央の帯に配置する。
- テキスト「AIを、収入に変える。」は1行で横に長く、画面の"ちょうど縦中央"に大きく配置。
- 画面の上側はシンプルな青空（白い四角いドット雲を少しだけ）。
- 画面の下側は8bitの土・地面のパターン。
  ※上下は「切り取られてOKな余白」として扱う。

【スタイル】
- 8ビット・ファミコン時代のレトロなドット絵（ピクセルアート）。横スクロールゲーム風。
- ※特定の商標・既存ゲームのキャラクターやロゴは一切描かない。汎用的な「8bitレトロゲーム風」。
- 緑の丘、レンガ模様のブロック、「？」ブロック、緑の土管、金色のコイン。
- 金色のコインは収入・マネタイズの象徴。ビビッドでポップな配色。

【テキスト】
- 「AIを、収入に変える。」を、8bitドット風の極太フォントで、誤字脱字なく正確に、くっきりと描く。
- 必ず画面の縦中央に。指定したテキスト以外の文字は描かない。

横長ワイドなバナー構図。出力は画像1枚のみ。前置き・後置きの文章は不要。"""


def _ensure_cdp_brave() -> None:
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


def _fit_to_note_header(src: Path, dst: Path) -> tuple[int, int]:
    """Fit *src* to note's recommended 1920x1006 header.

    Resizes to 1920 wide, then centers vertically — cropping if taller,
    or padding by replicating the flat 8-bit sky/ground edge rows if
    shorter. Centered content survives note's center-band crop.
    """
    from PIL import Image

    target_w, target_h = 1920, 1006
    im = Image.open(src).convert("RGB")
    w, h = im.size
    new_h = round(h * target_w / w)
    im = im.resize((target_w, new_h), Image.LANCZOS)
    if new_h >= target_h:
        top = (new_h - target_h) // 2
        im = im.crop((0, top, target_w, top + target_h))
    else:
        canvas = Image.new("RGB", (target_w, target_h))
        pad_top = (target_h - new_h) // 2
        pad_bot = target_h - new_h - pad_top
        # Replicate the flat 8-bit sky / ground edge rows — seamless.
        top_row = im.crop((0, 0, target_w, 1)).resize((target_w, pad_top))
        bot_row = im.crop(
            (0, new_h - 1, target_w, new_h)
        ).resize((target_w, pad_bot))
        canvas.paste(top_row, (0, 0))
        canvas.paste(im, (0, pad_top))
        canvas.paste(bot_row, (0, pad_top + new_h))
        im = canvas
    im.save(dst)
    return im.size


def main() -> int:
    _ensure_cdp_brave()
    from generators.chatgpt_image_generator import ChatGPTImageGenerator

    out_dir = _REPO / "data" / "images" / "profile"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    raw = out_dir / f"note_header_8bit_raw_{ts}.png"
    fitted = out_dir / f"note_header_8bit_fitted_{ts}.png"

    gen = ChatGPTImageGenerator(headless=False)
    ok = False
    try:
        gen._open_browser()
        try:
            gen._start_new_chat()
        except Exception as exc:  # noqa: BLE001
            logger.warning("new chat failed (%s) — continuing", exc)
        try:
            gen._send_prompt(_PROMPT)
            url = gen._wait_for_image(skip_urls=set())
            if url:
                gen._download_via_browser(url, raw)
                ok = True
                logger.info("raw image saved -> %s", raw)
            else:
                logger.error("no image found")
        except Exception as exc:  # noqa: BLE001
            logger.exception("generation failed: %s", exc)
        finally:
            try:
                gen._delete_current_chat()
            except Exception as exc:  # noqa: BLE001
                logger.warning("delete chat failed: %s", exc)
    finally:
        gen._close_browser()

    if not ok:
        print("RESULT: generation FAILED")
        return 1

    size = _fit_to_note_header(raw, fitted)
    print(f"RESULT: raw={raw}")
    print(f"RESULT: fitted={fitted} ({size[0]}x{size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
