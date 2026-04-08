"""Affiliate link injector.

Reads config/affiliates.yaml and appends relevant affiliate links
to generated articles based on title/content keyword matching.

Includes mandatory "PR" disclosure per Japanese stealth marketing
regulation (2023-10).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "affiliates.yaml"


class AffiliateInjector:
    """Insert affiliate links at the end of articles."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or _CONFIG_PATH
        self._config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        if not self._config_path.exists():
            logger.warning("Affiliate config not found: %s", self._config_path)
            return {}
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error("Failed to load affiliate config: %s", e)
            return {}

    def inject(self, content: str, title: str = "", platform: str = "") -> str:
        """Append affiliate links matched to article content.

        Args:
            content: Article body markdown
            title: Article title (used for keyword matching)
            platform: "note" or "zenn" (future: platform-specific behavior)

        Returns:
            Content with affiliate section appended
        """
        if not self._config:
            return content

        genre = self._detect_genre(title + " " + content)
        genre_config = self._config.get("genres", {}).get(genre, {})
        links = genre_config.get("links", [])

        if not links:
            # Fall back to default
            default_config = self._config.get("genres", {}).get("default", {})
            links = default_config.get("links", [])

        if not links:
            return content

        # Build the affiliate section
        disclosure = self._config.get("disclosure", "").strip()
        sections = [
            content.rstrip(),
            "",
            "## 関連リンク（PR）",
            "",
        ]
        for link in links:
            name = link.get("name", "")
            url = link.get("url", "")
            desc = link.get("description", "")
            if not url:
                continue
            sections.append(f"- [{name}]({url}) - {desc}")

        if disclosure:
            sections.append("")
            sections.append(disclosure)

        logger.info("Injected %d affiliate links for genre '%s'", len(links), genre)
        return "\n".join(sections)

    def _detect_genre(self, text: str) -> str:
        """Match article text against genre keywords and return best match."""
        genres = self._config.get("genres", {})
        best_genre = "default"
        best_score = 0

        for genre_name, genre_config in genres.items():
            if genre_name == "default":
                continue
            keywords = genre_config.get("keywords", [])
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                best_genre = genre_name

        logger.debug("Genre detected: %s (score=%d)", best_genre, best_score)
        return best_genre
