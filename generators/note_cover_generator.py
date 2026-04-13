"""note.com cover image generator (KENTO bear mascot edition).

Generates a 1280x720 PNG with centred Japanese typography, a yellow
highlight band on the second line, a contextual tag in the header, and
a small procedurally-drawn bear mascot whose scene (laptop, book, coin,
coffee, phone, ...) varies with the detected article genre.

Public API
----------
``NoteCoverGenerator.generate(title, genre=None, out_path=None) -> Path``

Design notes
------------
* Drawn entirely with PIL primitives — no external image assets needed.
* Japanese text uses Windows' Yu Gothic Bold.
* Title is split into up to two lines on a natural Japanese boundary
  (punctuation / particles) and falls back to a mid-string split.
* The bear is drawn small in the bottom-right corner so the title has
  the stage.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

W, H = 1280, 720

# --- Page palette (tech/AI 親しみ系 default) ---
BG = (255, 248, 231)
BG_NOISE = (245, 236, 214)
TAG_COLOUR = (120, 110, 90)
TEXT = (26, 26, 26)
HILITE_BG = (255, 216, 77)
HILITE_TEXT = (26, 26, 26)

# --- Bear palette ---
FUR = (198, 143, 82)
FUR_DARK = (150, 100, 52)
FUR_LIGHT = (220, 175, 120)
MUZZLE = (245, 220, 178)
NOSE = (50, 35, 25)
EYE = (28, 22, 18)
CHEEK = (240, 160, 140)

# --- Fonts (Windows) ---
FONT_BOLD = "C:/Windows/Fonts/YuGothB.ttc"
FONT_REG = "C:/Windows/Fonts/YuGothR.ttc"

# Break candidates (ordered by preference) — used to split the title
# into at most two lines
_BREAK_CHARS = "。！？!?・:：、, "

# Genre → tag line and scene key
_GENRE_META: dict[str, tuple[str, str]] = {
    "tech": ("AI・テック / tech-insight", "laptop"),
    "ai": ("AI・入門ガイド / beginner-friendly", "laptop"),
    "money": ("マネー・副業 / money-tips", "coin"),
    "learning": ("学び・スキル / learning", "book"),
    "food": ("グルメ・喫茶 / cafe-notes", "coffee"),
    "lifestyle": ("ライフ / lifestyle", "phone"),
    "beauty": ("美容・健康 / self-care", "phone"),
    "telecom": ("テック・ネット / telecom", "laptop"),
    "gaming": ("ゲーム / gaming", "laptop"),
    "default": ("note / kento", "laptop"),
}


class NoteCoverGenerator:
    """Draw a KENTO-branded note cover image from a title."""

    def __init__(self, out_dir: Path | None = None) -> None:
        self._out_dir = out_dir or (
            Path(__file__).resolve().parent.parent / "data" / "images" / "covers"
        )
        self._out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------
    def generate(
        self,
        title: str,
        genre: str | None = None,
        out_path: Path | None = None,
        slug: str = "cover",
    ) -> Path:
        """Draw a cover for *title* and return the saved path."""
        tag, scene = _GENRE_META.get(genre or "default", _GENRE_META["default"])
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)

        self._draw_paper_lines(d)
        self._draw_tag(d, tag)
        self._draw_title(d, title)
        self._draw_bear_scene(img, scene)

        path = out_path or (self._out_dir / f"{_sanitize_slug(slug)}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, "PNG", optimize=True)
        logger.info("Cover image saved: %s", path)
        return path

    # ------------------------------------------------------------------
    # Drawing helpers — page
    # ------------------------------------------------------------------
    @staticmethod
    def _draw_paper_lines(d: ImageDraw.ImageDraw) -> None:
        for i in range(0, H, 4):
            if (i // 4) % 7 == 0:
                d.rectangle([(0, i), (W, i + 1)], fill=BG_NOISE)

    @staticmethod
    def _draw_tag(d: ImageDraw.ImageDraw, tag: str) -> None:
        font = _load(FONT_REG, 26)
        tw, th = _text_size(d, tag, font)
        d.rectangle(
            [((W - tw) // 2 - 24, 70), ((W + tw) // 2 + 24, 72)], fill=TAG_COLOUR
        )
        d.text(((W - tw) // 2, 90), tag, font=font, fill=TAG_COLOUR)
        d.rectangle(
            [
                ((W - tw) // 2 - 24, 90 + th + 10),
                ((W + tw) // 2 + 24, 92 + th + 10),
            ],
            fill=TAG_COLOUR,
        )

    def _draw_title(self, d: ImageDraw.ImageDraw, title: str) -> None:
        # Pick a font size that fits within the frame (auto-shrink)
        line1, line2 = _split_two_lines(title)
        font_size = 92
        while font_size >= 48:
            font = _load(FONT_BOLD, font_size)
            w1, _ = _text_size(d, line1, font)
            w2, _ = _text_size(d, line2, font) if line2 else (0, 0)
            if max(w1, w2) <= W - 140:
                break
            font_size -= 6
        font = _load(FONT_BOLD, font_size)

        w1, h1 = _text_size(d, line1, font)
        if line2:
            w2, h2 = _text_size(d, line2, font)
        else:
            w2 = h2 = 0

        total_h = h1 + (h2 + 30 if line2 else 0)
        y1 = (H - total_h) // 2 - 20
        d.text(((W - w1) // 2, y1), line1, font=font, fill=TEXT)

        if line2:
            y2 = y1 + h1 + 30
            pad_x, pad_y = 26, 12
            x2 = (W - w2) // 2
            d.rectangle(
                [
                    (x2 - pad_x, y2 - pad_y + 6),
                    (x2 + w2 + pad_x, y2 + h2 + pad_y - 2),
                ],
                fill=HILITE_BG,
            )
            d.text((x2, y2), line2, font=font, fill=HILITE_TEXT)

    # ------------------------------------------------------------------
    # Drawing helpers — bear scenes
    # ------------------------------------------------------------------
    def _draw_bear_scene(self, base: Image.Image, scene: str) -> None:
        cx, cy = W - 130, H - 110
        scale = 0.62
        # All scenes share the same head/body; only the prop changes.
        prop = {
            "laptop": _prop_laptop,
            "book": _prop_book,
            "coin": _prop_coin,
            "coffee": _prop_coffee,
            "phone": _prop_phone,
        }.get(scene, _prop_laptop)
        _draw_bear(base, cx, cy, scale, prop=prop)


# ----------------------------------------------------------------------
# Bear drawing
# ----------------------------------------------------------------------
def _draw_bear(
    base: Image.Image,
    cx: int,
    cy: int,
    scale: float,
    prop,
) -> None:
    S = int(320 * scale)
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def s(v: float) -> int:
        return int(v * scale)

    # Body
    body_w, body_h = s(180), s(120)
    bx = S // 2 - body_w // 2
    by = s(150)
    d.ellipse((bx, by, bx + body_w, by + body_h), fill=FUR)
    bbw, bbh = s(110), s(80)
    d.ellipse(
        (S // 2 - bbw // 2, by + s(30), S // 2 - bbw // 2 + bbw, by + s(30) + bbh),
        fill=MUZZLE,
    )

    # Legs
    leg_r = s(22)
    d.ellipse(
        (bx + s(18), by + body_h - s(18), bx + s(18) + leg_r * 2, by + body_h - s(18) + leg_r * 2),
        fill=FUR_DARK,
    )
    d.ellipse(
        (bx + body_w - s(18) - leg_r * 2, by + body_h - s(18), bx + body_w - s(18), by + body_h - s(18) + leg_r * 2),
        fill=FUR_DARK,
    )

    # Arms
    arm_w, arm_h = s(32), s(50)
    d.ellipse((S // 2 - s(80), by + s(40), S // 2 - s(80) + arm_w, by + s(40) + arm_h), fill=FUR)
    d.ellipse((S // 2 + s(48), by + s(40), S // 2 + s(48) + arm_w, by + s(40) + arm_h), fill=FUR)

    # Prop in front of body
    prop(d, s, S, by)

    # Ears
    ear_r = s(26)
    d.ellipse((s(70), s(20), s(70) + ear_r * 2, s(20) + ear_r * 2), fill=FUR)
    d.ellipse((S - s(70) - ear_r * 2, s(20), S - s(70), s(20) + ear_r * 2), fill=FUR)
    inner = s(14)
    d.ellipse((s(78), s(30), s(78) + inner * 2, s(30) + inner * 2), fill=FUR_DARK)
    d.ellipse((S - s(78) - inner * 2, s(30), S - s(78), s(30) + inner * 2), fill=FUR_DARK)

    # Head
    d.ellipse((s(48), s(32), S - s(48), s(160)), fill=FUR)

    # Muzzle
    mw, mh = s(90), s(56)
    d.ellipse((S // 2 - mw // 2, s(88), S // 2 - mw // 2 + mw, s(88) + mh), fill=MUZZLE)

    # Nose
    nw, nh = s(20), s(14)
    d.ellipse((S // 2 - nw // 2, s(96), S // 2 - nw // 2 + nw, s(96) + nh), fill=NOSE)

    # Mouth
    mouth_cx = S // 2
    mouth_y = s(118)
    d.line([(mouth_cx, mouth_y), (mouth_cx - s(8), mouth_y + s(8))], fill=NOSE, width=max(2, s(3)))
    d.line([(mouth_cx, mouth_y), (mouth_cx + s(8), mouth_y + s(8))], fill=NOSE, width=max(2, s(3)))

    # Eyes
    eye_r = s(6)
    eye_y = s(80)
    d.ellipse((s(88) - eye_r, eye_y - eye_r, s(88) + eye_r, eye_y + eye_r), fill=EYE)
    d.ellipse((S - s(88) - eye_r, eye_y - eye_r, S - s(88) + eye_r, eye_y + eye_r), fill=EYE)
    d.ellipse((s(88) - 1, eye_y - s(3), s(88) + s(2), eye_y - s(3) + s(3)), fill=(255, 255, 255))
    d.ellipse((S - s(88) - 1, eye_y - s(3), S - s(88) + s(2), eye_y - s(3) + s(3)), fill=(255, 255, 255))

    # Cheeks
    cheek_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cheek_layer)
    cr = s(8)
    cy_ = s(104)
    cd.ellipse((s(70) - cr, cy_ - cr, s(70) + cr, cy_ + cr), fill=(*CHEEK, 130))
    cd.ellipse((S - s(70) - cr, cy_ - cr, S - s(70) + cr, cy_ + cr), fill=(*CHEEK, 130))
    cheek_layer = cheek_layer.filter(ImageFilter.GaussianBlur(radius=3))
    layer = Image.alpha_composite(layer, cheek_layer)

    base.paste(layer, (cx - S // 2, cy - S // 2), layer)


# --- Props -------------------------------------------------------------
def _prop_laptop(d, s, S, by) -> None:
    LAPTOP_BODY = (90, 95, 110)
    LAPTOP_SCREEN = (35, 42, 60)
    LAPTOP_GLOW = (90, 175, 240)
    lap_w, lap_h = s(150), s(22)
    lap_x = S // 2 - lap_w // 2
    lap_y = by + s(70)
    d.rounded_rectangle((lap_x, lap_y, lap_x + lap_w, lap_y + lap_h), radius=s(5), fill=LAPTOP_BODY)
    scr_w, scr_h = s(138), s(80)
    scr_x = S // 2 - scr_w // 2
    scr_y = lap_y - scr_h + s(2)
    d.rounded_rectangle((scr_x, scr_y, scr_x + scr_w, scr_y + scr_h), radius=s(6), fill=LAPTOP_BODY)
    d.rounded_rectangle(
        (scr_x + s(6), scr_y + s(6), scr_x + scr_w - s(6), scr_y + scr_h - s(6)),
        radius=s(4),
        fill=LAPTOP_SCREEN,
    )
    font = _load(FONT_BOLD, s(32))
    tw, th = _text_size(d, "AI", font)
    d.text(
        (scr_x + scr_w // 2 - tw // 2, scr_y + scr_h // 2 - th // 2 - s(4)),
        "AI",
        font=font,
        fill=LAPTOP_GLOW,
    )


def _prop_book(d, s, S, by) -> None:
    bw, bh = s(140), s(90)
    bx = S // 2 - bw // 2
    by_ = by + s(35)
    d.rounded_rectangle((bx, by_, bx + bw, by_ + bh), radius=s(4), fill=(180, 60, 60))
    d.rounded_rectangle(
        (bx + s(8), by_ + s(8), bx + bw - s(8), by_ + bh - s(8)), radius=s(2), fill=(245, 230, 200)
    )
    # Center spine
    d.line([(S // 2, by_ + s(6)), (S // 2, by_ + bh - s(6))], fill=(120, 40, 40), width=max(2, s(2)))
    # Text lines on pages
    for i in range(3):
        y = by_ + s(20) + i * s(14)
        d.line([(bx + s(14), y), (S // 2 - s(6), y)], fill=(160, 140, 100), width=max(1, s(2)))
        d.line([(S // 2 + s(6), y), (bx + bw - s(14), y)], fill=(160, 140, 100), width=max(1, s(2)))


def _prop_coin(d, s, S, by) -> None:
    cr = s(38)
    cx = S // 2
    cy_ = by + s(75)
    d.ellipse((cx - cr, cy_ - cr, cx + cr, cy_ + cr), fill=(255, 200, 60), outline=(180, 130, 20), width=max(2, s(3)))
    font = _load(FONT_BOLD, s(38))
    tw, th = _text_size(d, "¥", font)
    d.text((cx - tw // 2, cy_ - th // 2 - s(4)), "¥", font=font, fill=(120, 80, 10))


def _prop_coffee(d, s, S, by) -> None:
    cup_w, cup_h = s(110), s(80)
    cx = S // 2 - cup_w // 2
    cy_ = by + s(45)
    d.rounded_rectangle((cx, cy_, cx + cup_w, cy_ + cup_h), radius=s(10), fill=(245, 240, 230), outline=(80, 60, 40), width=max(2, s(2)))
    # Coffee
    d.ellipse((cx + s(8), cy_ + s(6), cx + cup_w - s(8), cy_ + s(26)), fill=(80, 50, 20))
    # Handle
    d.arc(
        (cx + cup_w - s(10), cy_ + s(15), cx + cup_w + s(20), cy_ + s(55)),
        start=270,
        end=90,
        fill=(80, 60, 40),
        width=max(3, s(4)),
    )
    # Steam
    for off in (-s(18), 0, s(18)):
        d.line(
            [(cx + cup_w // 2 + off, cy_ - s(10)), (cx + cup_w // 2 + off + s(6), cy_ - s(22))],
            fill=(180, 180, 180),
            width=max(2, s(2)),
        )


def _prop_phone(d, s, S, by) -> None:
    pw, ph = s(60), s(100)
    px = S // 2 - pw // 2
    py = by + s(35)
    d.rounded_rectangle((px, py, px + pw, py + ph), radius=s(8), fill=(40, 45, 60))
    d.rounded_rectangle(
        (px + s(5), py + s(10), px + pw - s(5), py + ph - s(10)), radius=s(4), fill=(90, 175, 240)
    )
    # A tiny app icon grid
    for row in range(3):
        for col in range(2):
            r = s(4)
            ix = px + s(12) + col * s(18)
            iy = py + s(20) + row * s(18)
            d.ellipse((ix, iy, ix + r * 2, iy + r * 2), fill=(255, 255, 255))


# ----------------------------------------------------------------------
# Text utilities
# ----------------------------------------------------------------------
def _load(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def _split_two_lines(title: str) -> tuple[str, str]:
    """Split *title* into at most two lines for the cover."""
    title = title.strip()
    if len(title) <= 14:
        return title, ""
    # Prefer a break character near the middle (±25% window)
    mid = len(title) // 2
    window = max(3, len(title) // 4)
    best = -1
    for i in range(mid - window, mid + window + 1):
        if 0 < i < len(title) and title[i] in _BREAK_CHARS:
            if best == -1 or abs(i - mid) < abs(best - mid):
                best = i
    if best != -1:
        return title[: best + 1].rstrip(), title[best + 1 :].lstrip()
    # Fallback: hard split near middle
    return title[:mid].rstrip(), title[mid:].lstrip()


_SLUG_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


def _sanitize_slug(slug: str) -> str:
    safe = _SLUG_RE.sub("_", slug).strip("_")
    return (safe or "cover")[:80]


if __name__ == "__main__":  # pragma: no cover — manual smoke test
    logging.basicConfig(level=logging.INFO)
    gen = NoteCoverGenerator()
    for t, g in [
        ("AIの使い方講座！！初心者にもやさしい！！", "ai"),
        ("月10万円を副業で稼ぐ7つの現実的手段", "money"),
        ("渋谷レトロ喫茶のコーヒーゼリー", "food"),
        ("ChatGPTで効率化する学習ルーティン", "learning"),
    ]:
        gen.generate(t, genre=g, slug=t[:12])
