"""Cover image generator for Zenn and note articles.

Creates eye-catching thumbnail/cover images using:
1. Stock photo background + title text overlay (Pillow)
2. Gradient template + title (no API needed)
3. AI-generated images via Ollama (v1.1, requires GPU)

Output: 1200x630 OGP-compliant images for maximum platform compatibility.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# OGP recommended size
COVER_WIDTH = 1200
COVER_HEIGHT = 630

# Color themes by category
THEMES: dict[str, dict] = {
    "tech": {
        "gradient_start": (15, 23, 42),      # dark navy
        "gradient_end": (30, 64, 175),        # blue
        "accent": (56, 189, 248),             # cyan
        "text_color": (255, 255, 255),
    },
    "korean": {
        "gradient_start": (131, 24, 67),      # dark pink
        "gradient_end": (219, 39, 119),        # pink
        "accent": (251, 191, 36),             # gold
        "text_color": (255, 255, 255),
    },
    "coffee": {
        "gradient_start": (41, 21, 10),       # dark brown
        "gradient_end": (120, 63, 4),         # brown
        "accent": (217, 164, 106),            # latte
        "text_color": (255, 255, 255),
    },
    "gourmet": {
        "gradient_start": (55, 7, 2),         # dark red
        "gradient_end": (185, 28, 28),         # red
        "accent": (252, 211, 77),             # gold
        "text_color": (255, 255, 255),
    },
    "beauty": {
        "gradient_start": (76, 29, 149),      # purple
        "gradient_end": (192, 38, 211),        # magenta
        "accent": (249, 168, 212),            # pink
        "text_color": (255, 255, 255),
    },
    "lifestyle": {
        "gradient_start": (6, 78, 59),        # dark green
        "gradient_end": (5, 150, 105),         # emerald
        "accent": (167, 243, 208),            # mint
        "text_color": (255, 255, 255),
    },
    "default": {
        "gradient_start": (17, 24, 39),       # gray-900
        "gradient_end": (55, 65, 81),          # gray-700
        "accent": (99, 102, 241),             # indigo
        "text_color": (255, 255, 255),
    },
}

# Keywords → theme mapping
THEME_KEYWORDS: dict[str, list[str]] = {
    "tech": ["AI", "LLM", "Python", "プログラミング", "エンジニア", "開発",
             "技術", "API", "クラウド", "セキュリティ"],
    "korean": ["韓国", "K-POP", "韓流", "Kビューティー", "韓国コスメ"],
    "coffee": ["コーヒー", "バリスタ", "カフェ", "エスプレッソ", "焙煎", "珈琲"],
    "gourmet": ["居酒屋", "グルメ", "レストラン", "デート", "モテ", "食べ歩き"],
    "beauty": ["美容", "コスメ", "スキンケア", "メイク", "美意識"],
    "lifestyle": ["ライフスタイル", "暮らし", "ファッション", "自分磨き"],
}


class CoverGenerator:
    """Generate cover/thumbnail images for articles.

    Creates 1200x630 OGP-compliant images with:
    - Gradient or stock photo background
    - Title text with shadow for readability
    - Category accent stripe
    - Platform badge (Zenn/note)
    """

    def __init__(self, output_dir: str = "docs/images/covers") -> None:
        """Initialize cover generator.

        Args:
            output_dir: Directory to save generated cover images.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._font_path = self._find_japanese_font()

    def generate(
        self,
        title: str,
        platform: str = "note",
        background_image_path: Optional[str] = None,
        slug: str = "article",
    ) -> str:
        """Generate a cover image for an article.

        Args:
            title: Article title (displayed on the cover).
            platform: "zenn" or "note".
            background_image_path: Optional path to a stock photo for background.
            slug: Used for the output filename.

        Returns:
            Path to the generated cover image.
        """
        theme = self._detect_theme(title)

        if background_image_path and Path(background_image_path).exists():
            img = self._create_photo_cover(
                title, background_image_path, theme, platform
            )
        else:
            img = self._create_gradient_cover(title, theme, platform)

        output_path = self.output_dir / f"{slug}_cover.png"
        img.save(str(output_path), "PNG", quality=95)
        logger.info("Cover image generated: %s", output_path)
        return str(output_path)

    def _create_gradient_cover(
        self, title: str, theme: dict, platform: str
    ) -> Image.Image:
        """Create a cover with gradient background + title text."""
        img = Image.new("RGB", (COVER_WIDTH, COVER_HEIGHT))
        draw = ImageDraw.Draw(img)

        # Gradient background
        self._draw_gradient(draw, theme["gradient_start"], theme["gradient_end"])

        # Accent stripe (top)
        accent = theme["accent"]
        draw.rectangle(
            [(0, 0), (COVER_WIDTH, 6)],
            fill=accent,
        )

        # Platform badge
        self._draw_platform_badge(draw, platform, accent)

        # Title text
        self._draw_title(draw, title, theme["text_color"])

        # Decorative dots
        self._draw_decoration(draw, accent)

        return img

    def _create_photo_cover(
        self, title: str, photo_path: str, theme: dict, platform: str
    ) -> Image.Image:
        """Create a cover with stock photo background + dark overlay + title."""
        bg = Image.open(photo_path).convert("RGB")
        bg = bg.resize((COVER_WIDTH, COVER_HEIGHT), Image.LANCZOS)

        # Dark overlay for text readability
        overlay = Image.new("RGBA", bg.size, (0, 0, 0, 140))
        img = bg.convert("RGBA")
        img = Image.alpha_composite(img, overlay).convert("RGB")

        draw = ImageDraw.Draw(img)

        # Accent stripe
        accent = theme["accent"]
        draw.rectangle([(0, 0), (COVER_WIDTH, 6)], fill=accent)

        # Platform badge
        self._draw_platform_badge(draw, platform, accent)

        # Title text (white for readability on dark overlay)
        self._draw_title(draw, title, (255, 255, 255))

        return img

    def _draw_gradient(
        self, draw: ImageDraw.Draw, start: tuple, end: tuple
    ) -> None:
        """Draw a vertical gradient."""
        for y in range(COVER_HEIGHT):
            ratio = y / COVER_HEIGHT
            r = int(start[0] + (end[0] - start[0]) * ratio)
            g = int(start[1] + (end[1] - start[1]) * ratio)
            b = int(start[2] + (end[2] - start[2]) * ratio)
            draw.line([(0, y), (COVER_WIDTH, y)], fill=(r, g, b))

    def _draw_title(
        self, draw: ImageDraw.Draw, title: str, color: tuple
    ) -> None:
        """Draw article title with line wrapping and shadow."""
        font_size = 52
        font = self._get_font(font_size)
        shadow_color = (0, 0, 0)

        # Wrap text to fit
        lines = self._wrap_text(title, font, COVER_WIDTH - 120)

        # Calculate vertical position (centered)
        line_height = font_size + 12
        total_height = len(lines) * line_height
        y_start = (COVER_HEIGHT - total_height) // 2

        for i, line in enumerate(lines):
            x = 60
            y = y_start + i * line_height

            # Shadow
            draw.text((x + 2, y + 2), line, font=font, fill=shadow_color)
            # Text
            draw.text((x, y), line, font=font, fill=color)

    def _draw_platform_badge(
        self, draw: ImageDraw.Draw, platform: str, accent: tuple
    ) -> None:
        """Draw a small platform badge in the top-right corner."""
        badge_font = self._get_font(20)
        badge_text = "Zenn" if platform == "zenn" else "note"
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        text_w = bbox[2] - bbox[0]

        x = COVER_WIDTH - text_w - 30
        y = 20
        # Badge background
        draw.rounded_rectangle(
            [(x - 10, y - 5), (x + text_w + 10, y + 25)],
            radius=5,
            fill=accent,
        )
        draw.text((x, y), badge_text, font=badge_font, fill=(255, 255, 255))

    def _draw_decoration(
        self, draw: ImageDraw.Draw, accent: tuple
    ) -> None:
        """Draw decorative elements."""
        # Bottom-right dots
        for i in range(3):
            x = COVER_WIDTH - 60 + i * 20
            y = COVER_HEIGHT - 40
            draw.ellipse(
                [(x, y), (x + 8, y + 8)],
                fill=(*accent, 128) if len(accent) == 3 else accent,
            )

    def _wrap_text(
        self, text: str, font, max_width: int
    ) -> list[str]:
        """Wrap text to fit within max_width pixels."""
        lines: list[str] = []
        current = ""

        for char in text:
            test = current + char
            bbox = font.getbbox(test)
            if bbox[2] > max_width:
                if current:
                    lines.append(current)
                current = char
            else:
                current = test

        if current:
            lines.append(current)

        return lines[:4]  # Max 4 lines

    def _detect_theme(self, title: str) -> dict:
        """Detect the best color theme based on title keywords."""
        title_lower = title.lower()
        for theme_name, keywords in THEME_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in title_lower:
                    logger.debug("Theme detected: %s", theme_name)
                    return THEMES[theme_name]
        return THEMES["default"]

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Get a Japanese-capable font at the specified size."""
        if self._font_path:
            try:
                return ImageFont.truetype(self._font_path, size)
            except (OSError, IOError):
                pass
        return ImageFont.load_default()

    @staticmethod
    def _find_japanese_font() -> Optional[str]:
        """Find a Japanese font available on the system."""
        candidates = [
            # Windows
            "C:/Windows/Fonts/meiryo.ttc",
            "C:/Windows/Fonts/msgothic.ttc",
            "C:/Windows/Fonts/YuGothM.ttc",
            "C:/Windows/Fonts/BIZ-UDGothicR.ttc",
            # macOS
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            # Linux
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
        for path in candidates:
            if os.path.exists(path):
                logger.debug("Japanese font found: %s", path)
                return path
        logger.warning("No Japanese font found. Text may render incorrectly.")
        return None
