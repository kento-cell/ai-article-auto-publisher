"""Affiliate link injector.

Reads config/affiliates.yaml (template with ${ENV_VAR} placeholders)
and substitutes values from environment variables at runtime.

Security: Real ASP IDs are stored in .env (gitignored), not in the
YAML template. This allows safe git commits without leaking
affiliate identifiers.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "affiliates.yaml"
_ENV_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
# HTML-comment sentinel marking an injected affiliate section. Used as
# the authoritative idempotency check; the visible heading alone is
# unreliable (users may write their own "## 関連リンク" sections in
# article bodies, and the heading text may drift).
_AFFILIATE_SENTINEL = "<!-- AFFILIATE_SECTION -->"


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
                raw = f.read()
            # Substitute ${ENV_VAR} with actual env values
            def _substitute(match: re.Match[str]) -> str:
                var_name = match.group(1)
                value = os.environ.get(var_name, "")
                if not value:
                    logger.debug("Env var %s not set", var_name)
                return value
            substituted = _ENV_VAR_RE.sub(_substitute, raw)
            return yaml.safe_load(substituted) or {}
        except Exception as e:
            logger.error("Failed to load affiliate config: %s", e)
            return {}

    @staticmethod
    def _is_valid_link(url: str) -> bool:
        """Check if URL is usable (not empty and not a placeholder)."""
        if not url:
            return False
        # Skip URLs that still contain unresolved placeholders
        if "${" in url or "YOURTAG" in url:
            return False
        return True

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

        # Idempotency guard: never double-inject.
        if _AFFILIATE_SENTINEL in content:
            logger.debug("Affiliate sentinel present; skipping inject")
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

        # Filter out invalid/unresolved links
        valid_links = [l for l in links if self._is_valid_link(l.get("url", ""))]
        if not valid_links:
            return content

        # Build the affiliate section (minimal gray-zone disclosure)
        disclosure = self._config.get("disclosure", "").strip()
        # Preserve trailing whitespace on the final content line; only strip
        # trailing newlines so that the affiliate section lands with a clean
        # one-blank-line separator.
        sections = [
            content.rstrip("\n"),
            "",
            _AFFILIATE_SENTINEL,
            "## 関連リンク",
            "",
        ]
        for link in valid_links:
            name = link.get("name", "")
            url = link.get("url", "")
            desc = link.get("description", "")
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
