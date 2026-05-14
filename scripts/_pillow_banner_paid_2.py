"""Generate paid-tier text-overlay banners for the 2 reworked paid notes
using Pillow, then edit_article with new_title + body + cover.

Why Pillow not ChatGPT (2026-05-14): ChatGPT image gen was producing
bit-identical 23KB note-logo PNGs across all 11 outputs (verified via
md5sum). The _start_new_chat() path on launch_persistent_context didn't
actually start a new chat, and CF Turnstile blocked CDP attach. Until
that's properly fixed, Pillow banners are deterministic, fast (<1s
each), and look professional with the right typography.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Disable ChatGPT vision-eval (publisher might still pull it in)
os.environ.setdefault("CHATGPT_VISION_EVAL", "0")
os.environ.setdefault("USE_CHATGPT_IMAGES", "0")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pillow_banner")


W, H = 1280, 720  # 16:9 — note cover sweet spot

# Theme-keyed color palettes. (bg, accent, text-on-bg, text-on-accent)
THEMES = {
    "wasp": {
        "bg":    (28, 27, 60),       # deep navy
        "accent": (255, 209, 60),    # warm yellow
        "text_bg": (255, 255, 255),
        "text_accent": (28, 27, 60),
        "tagline_bg": (255, 209, 60),
    },
    "cisco": {
        "bg":    (10, 45, 75),       # corporate navy
        "accent": (220, 80, 60),     # caution red
        "text_bg": (255, 255, 255),
        "text_accent": (255, 255, 255),
        "tagline_bg": (220, 80, 60),
    },
}


FONT_BOLD = r"C:\Windows\Fonts\YuGothB.ttc"
FONT_MEDIUM = r"C:\Windows\Fonts\YuGothM.ttc"


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy Japanese-friendly wrap (character-level).

    Respects explicit ``\\n`` newlines in the input — they're hard line
    breaks and never merged with surrounding characters.
    """
    lines: list[str] = []
    for raw_line in text.split("\n"):
        cur = ""
        for ch in raw_line:
            test = cur + ch
            bbox = font.getbbox(test)
            if bbox[2] - bbox[0] > max_width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        lines.append(cur)
    return lines


def make_banner(
    bracket: str,        # e.g. 【完全暴露】
    headline: str,       # e.g. Wasp 創業者が $5M と5年を溶かして気づいた
    tagline: str,        # e.g. DSL を作るのは堀じゃなかった
    theme: dict,
    out_path: Path,
) -> Path:
    img = Image.new("RGB", (W, H), theme["bg"])
    draw = ImageDraw.Draw(img)

    # Accent diagonal block (lower-right wedge)
    points = [(W * 0.55, H), (W, H * 0.35), (W, H), (W * 0.55, H)]
    draw.polygon(points, fill=theme["accent"])

    # Bracket tag (top-left, on accent background)
    bracket_font = ImageFont.truetype(FONT_BOLD, 56)
    bbox = bracket_font.getbbox(bracket)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 24
    draw.rectangle(
        (60, 60, 60 + bw + pad * 2, 60 + bh + pad * 2),
        fill=theme["tagline_bg"],
    )
    draw.text(
        (60 + pad, 60 + pad - 12),
        bracket,
        font=bracket_font,
        fill=theme["text_accent"],
    )

    # Main headline (wraps across multiple lines)
    headline_font = ImageFont.truetype(FONT_BOLD, 64)
    margin = 60
    max_text_w = int(W * 0.85)
    lines = _wrap_text(headline, headline_font, max_text_w)
    y = 220
    for line in lines[:3]:
        draw.text(
            (margin, y), line, font=headline_font, fill=theme["text_bg"],
        )
        y += 78

    # Tagline (smaller, separated)
    tagline_font = ImageFont.truetype(FONT_MEDIUM, 38)
    tl_lines = _wrap_text(tagline, tagline_font, max_text_w)
    y += 30
    for line in tl_lines[:2]:
        draw.text(
            (margin, y), line, font=tagline_font, fill=theme["text_bg"],
        )
        y += 50

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    logger.info("banner saved: %s (%d bytes)", out_path, out_path.stat().st_size)
    return out_path


JOBS = [
    {
        "article_id": "note-5_Years_and__5M_Late-f1b21453",
        "url": "https://note.com/note-user/n/nc46a11cd674e",
        "new_title": "【完全暴露】Wasp 創業者が $5M と5年を溶かして気づいた「DSL を作るのは堀じゃなかった」— Y Combinator 出身チームの正直すぎる反省録",
        "banner": {
            "bracket": "【完全暴露】",
            "headline": "$5M と5年溶かした\n創業者の反省録",
            "tagline": "DSL は堀じゃなかった — Wasp の方向転換",
            "theme": THEMES["wasp"],
        },
    },
    {
        "article_id": "note-Cisco_s_stock_pops_1-5224bf4f",
        "url": "https://note.com/note-user/n/n7846dd3ea6a7",
        "new_title": "【速報・完全分析】Cisco 株価+17% と4000人解雇が同日に起きた「2026年5月13日」— AI 受注 $5.3B が示す通信機器メーカーの再定義",
        "banner": {
            "bracket": "【速報・完全分析】",
            "headline": "株価+17% & 4000人解雇\n同日に起きた異変",
            "tagline": "Cisco AI 受注 $5.3B が示す通信機器の再定義",
            "theme": THEMES["cisco"],
        },
    },
]


def main() -> int:
    subprocess.run(
        ["taskkill", "/F", "/IM", "brave.exe"],
        check=False, capture_output=True,
    )
    time.sleep(2)

    articles_dir = _REPO / "data" / "articles"
    covers_dir = _REPO / "data" / "images" / "covers"

    # Phase 1 — generate banners
    for j in JOBS:
        bp = covers_dir / f"pillow_paid_{j['article_id']}_cover.png"
        make_banner(out_path=bp, **j["banner"])
        j["cover_path"] = bp
        # Persist new path + title into article JSON
        ap = articles_dir / f"{j['article_id']}.json"
        d = json.loads(ap.read_text(encoding="utf-8"))
        d["_cover_image_before_pillow"] = d.get("cover_image")
        d["cover_image"] = str(bp.relative_to(_REPO))
        d["title"] = j["new_title"]
        ap.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("article json updated: %s", ap)

    # Phase 2 — edit_article with title + content + cover
    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[str] = []
    try:
        for j in JOBS:
            ap = articles_dir / f"{j['article_id']}.json"
            d = json.loads(ap.read_text(encoding="utf-8"))
            body = d.get("content", "")
            # Drop any leading H2 that duplicates the title — note shows the
            # title as H1 automatically and the body shouldn't repeat it.
            lines = body.splitlines()
            if lines and lines[0].startswith("## ") and j["new_title"][:10] in lines[0]:
                body = "\n".join(lines[1:]).lstrip()
            # Drop local-image markdown lines so edit re-uploads inline images
            # via paste handler.
            body = re.sub(
                r"\n?!\[[^\]]*\]\(data/images/[^)\s]+(?:\s+\"[^\"]*\")?\)\n?",
                "\n", body,
            )
            logger.info("Editing %s", j["url"])
            try:
                ok = pub.edit_article(
                    url=j["url"],
                    new_title=j["new_title"],
                    new_content=body,
                    inline_image_paths=None,
                    cover_image_path=str(j["cover_path"].resolve()),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("  OK: %s", j["url"])
            else:
                failed.append(j["url"])
                logger.error("  FAIL: %s", j["url"])
            time.sleep(4)
    finally:
        pub.close()

    logger.info("DONE — uploaded=%d failed=%d", succeeded, len(failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
