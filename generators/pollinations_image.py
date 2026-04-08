"""Pollinations.ai cover image generator (zero-cost).

Uses the free https://image.pollinations.ai/ service to generate cover
images from article titles. No API key required.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

_POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"
_DEFAULT_WIDTH = 1200
_DEFAULT_HEIGHT = 630  # note/Zenn cover ratio
_TIMEOUT = 90


class PollinationsImageGenerator:
    """Generate cover images via Pollinations.ai (free, no key)."""

    def __init__(self, output_dir: str | Path = "data/images/covers") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate_cover(
        self,
        title: str,
        slug: str,
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
        model: str = "flux",
    ) -> Path | None:
        """Generate a cover image from article title.

        Args:
            title: Article title (Japanese or English)
            slug: Filename slug
            width: Image width
            height: Image height
            model: Model name (flux, turbo, etc.)

        Returns:
            Path to generated image, or None on failure
        """
        prompt = self._build_prompt(title)
        encoded = quote(prompt)
        url = _POLLINATIONS_URL.format(prompt=encoded)
        params = {
            "width": width,
            "height": height,
            "model": model,
            "nologo": "true",
            "enhance": "true",
        }

        safe_slug = re.sub(r'[\\/:*?"<>|]', "_", slug)[:80]
        output_path = self._output_dir / f"{safe_slug}_cover.png"

        try:
            logger.info("Generating cover via Pollinations: %s", title[:40])
            resp = requests.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            output_path.write_bytes(resp.content)
            logger.info("Cover saved: %s (%d bytes)", output_path, len(resp.content))
            return output_path
        except requests.exceptions.RequestException as e:
            logger.warning("Pollinations cover generation failed: %s", e)
            return None

    @staticmethod
    def _build_prompt(title: str) -> str:
        """Convert article title to a visual prompt for image generation."""
        # Remove Japanese particles and punctuation
        cleaned = re.sub(r"[、。！？「」『』【】\(\)（）]", " ", title)
        cleaned = re.sub(r"[のがをはへでとにから]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Detect theme from keywords
        themes = {
            "ai": "artificial intelligence, neural network",
            "AI": "artificial intelligence, neural network",
            "LLM": "language model, AI brain",
            "エージェント": "AI agent, robot",
            "自動": "automation, robotic workflow",
            "Zenn": "tech blog, code editor",
            "note": "writing, notebook",
            "Python": "Python programming, code",
            "コード": "code, programming",
            "マネタイズ": "business, money, entrepreneurship",
            "月収": "income growth chart, money",
            "副業": "side hustle, multiple monitors",
            "グルメ": "food photography, restaurant",
            "韓国": "korean culture, seoul",
            "美容": "beauty, cosmetics",
            "コーヒー": "coffee cafe, espresso",
        }

        style_parts = []
        for keyword, theme in themes.items():
            if keyword in title:
                style_parts.append(theme)

        if not style_parts:
            style_parts.append("modern tech illustration")

        # Build final prompt
        visual_style = (
            "cinematic lighting, professional photography, "
            "high quality, 8k, detailed, vibrant colors, "
            "blog cover image, wide aspect ratio"
        )
        prompt = f"{cleaned}, {', '.join(style_parts)}, {visual_style}"
        return prompt[:500]  # URL length safety
