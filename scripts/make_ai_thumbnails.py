"""Overlay titles on the user-prepared base images and set them as
note eyecatch covers for AI-related articles.

Base images (from data/thumbnails/src/img/):
  - ClaudexMario.png          — pixel-Mario world with { } < > brackets
  - ClaudeｘFallOut.png        — Fallout Vault-Boy style, CRT green on black
  - Pokemon x AI.png          — Pokemon battle scene, ChatGPT logo opponent

Each image has a distinct empty zone for the title text, reflected in
the per-image placement config below. The font is the stock Windows
NotoSansJP-VF so the output is a clean, reproducible Japanese render.

Usage:
    py -X utf8 scripts/make_ai_thumbnails.py          # preview only
    py -X utf8 scripts/make_ai_thumbnails.py --apply  # also upload
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

if sys.platform == "win32" and __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import logging  # noqa: E402
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("make_ai_thumbnails")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

_FONT_PATH = Path("C:/Windows/Fonts/NotoSansJP-VF.ttf")
_SRC_DIR = _REPO / "data" / "thumbnails" / "src" / "img"
_OUT_DIR = _REPO / "data" / "thumbnails" / "built"
_OUT_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Per-image placement config
#
# - bbox: (x, y, w, h) — drawable area on the image.
# - lines: list of (text, font_size).
# - color: title text colour.
# - outline: outline colour, thickness 3.
# - anchor: "center" / "left" / "right" relative to bbox x axis.
# =============================================================================


def _draw_title(
    img_path: Path,
    lines: list[tuple[str, int]],
    bbox: tuple[int, int, int, int],
    color: tuple[int, int, int],
    outline: tuple[int, int, int] | None,
    anchor: str,
) -> Image.Image:
    im = Image.open(img_path).convert("RGBA")
    draw = ImageDraw.Draw(im)

    bx, by, bw, bh = bbox

    # Vertical stacking with line spacing = 0.2 * font_size
    rendered: list[tuple[ImageFont.FreeTypeFont, str, int, int]] = []
    total_h = 0
    for text, size in lines:
        font = ImageFont.truetype(str(_FONT_PATH), size)
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        w, h = r - l, b - t
        rendered.append((font, text, w, h))
        total_h += h + int(size * 0.25)
    total_h -= int(lines[-1][1] * 0.25)

    # Start Y: top-align within bbox (center vertically)
    start_y = by + max(0, (bh - total_h) // 2)
    cursor_y = start_y
    for font, text, w, h in rendered:
        if anchor == "center":
            x = bx + (bw - w) // 2
        elif anchor == "right":
            x = bx + bw - w
        else:
            x = bx
        # Simple outline via 4-offset draws for readability on noisy
        # pixel-art backgrounds.
        if outline is not None:
            for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3),
                           (-2, -2), (-2, 2), (2, -2), (2, 2)):
                draw.text((x + dx, cursor_y + dy), text, font=font, fill=outline)
        draw.text((x, cursor_y), text, font=font, fill=color)
        cursor_y += h + int(font.size * 0.25)

    return im.convert("RGB")


# =============================================================================
# Article mapping — (article_key, image_base, title_config)
# =============================================================================

_TARGETS: list[dict] = [
    {
        "key": "na1defe84b0a0",
        "title_display": "【コアメンバー】AI活用：Geminiを「秘書」にする",
        "src_image": "ClaudexMario(背景余白にタイトルやキャッチフレーズ入力).png",
        # The image is 864×432ish. Top sky area is clean; put a 2-line
        # title there. Colors: white with black outline for pixel-art
        # legibility against the sky gradient.
        "lines": [
            ("Geminiを「秘書」にする", 54),
            ("AI活用 実務ロードマップ", 40),
        ],
        "bbox_fn": lambda w, h: (
            int(w * 0.04), int(h * 0.05),
            int(w * 0.92), int(h * 0.35),
        ),
        "color": (255, 255, 255),
        "outline": (0, 0, 0),
        "anchor": "center",
    },
    {
        "key": "nf6b8a333cf19",
        "title_display": "【そもそも解説】日本の鉄道×AI、何が「本当に」動いているのか",
        "src_image": "ClaudeｘFallOut(背景左の余白にタイトルやキャッチフレーズ入力).png",
        # Left dark area is the title zone. Fallout aesthetic:
        # phosphor green on the black CRT surface.
        "lines": [
            ("日本の鉄道 × AI", 52),
            ("本当に動いている", 42),
            ("導入事例だけ並べる", 38),
        ],
        "bbox_fn": lambda w, h: (
            int(w * 0.05), int(h * 0.18),
            int(w * 0.56), int(h * 0.64),
        ),
        "color": (76, 255, 76),
        "outline": (0, 40, 0),
        "anchor": "left",
    },
    # Spare — used when a future AI article lands.
    {
        "key": None,
        "title_display": "PLACEHOLDER — 次のAI記事用",
        "src_image": "Pokemon x AI(画像内テキストボックスにタイトルやキャッチフレーズ入力).png",
        "lines": [
            ("AI時代の", 44),
            ("新しい戦い方", 40),
        ],
        # The dialog box is at the bottom of the image.
        "bbox_fn": lambda w, h: (
            int(w * 0.06), int(h * 0.72),
            int(w * 0.88), int(h * 0.24),
        ),
        "color": (40, 40, 40),
        "outline": None,
        "anchor": "left",
    },
]


def _build() -> list[tuple[Path, dict]]:
    built: list[tuple[Path, dict]] = []
    for t in _TARGETS:
        src = _SRC_DIR / t["src_image"]
        if not src.exists():
            print(f"[skip] source missing: {t['src_image']}")
            continue
        im = Image.open(src)
        w, h = im.size
        bbox = t["bbox_fn"](w, h)
        result = _draw_title(
            img_path=src,
            lines=t["lines"],
            bbox=bbox,
            color=t["color"],
            outline=t["outline"],
            anchor=t["anchor"],
        )
        out = _OUT_DIR / f"thumb_{t['key'] or 'spare'}.jpg"
        result.save(out, "JPEG", quality=92)
        print(f"[built] {out.name} ({out.stat().st_size} bytes)")
        built.append((out, t))
    return built


def _apply(built: list[tuple[Path, dict]]) -> int:
    from publishers.note_publisher import NotePublisher

    apply_targets = [(p, t) for p, t in built if t["key"]]
    if not apply_targets:
        print("No applicable articles (all placeholders).")
        return 0

    pub = NotePublisher(headless=False)
    try:
        for path, t in apply_targets:
            url = f"https://note.com/{os.environ.get('NOTE_USER', '')}/n/{t['key']}"
            print(f"[apply] {t['key']} → {path.name}")
            try:
                ok = pub.edit_article(
                    url=url,
                    new_title=None,       # keep
                    new_content=None,     # keep
                    inline_image_paths=None,
                    cover_image_path=str(path.resolve()),
                )
                print(f"  result: {'OK' if ok else 'FAIL'}")
            except Exception as exc:
                print(f"  error: {exc}")
    finally:
        pub.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="upload thumbnails to note.com")
    args = parser.parse_args()

    built = _build()
    if args.apply:
        _apply(built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
