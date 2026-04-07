"""Copyright-safe image sourcing from free stock photo APIs.

Searches Unsplash and Pexels for royalty-free images and generates
attribution strings suitable for Markdown articles.  Falls back to
SVG placeholder generation when no API keys are configured.

Dependencies: requests, os
"""

import logging
import os
import re
from typing import Optional
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed licenses -- only these are considered safe to use.
# ---------------------------------------------------------------------------
_ALLOWED_LICENSES = frozenset({"CC0", "Unsplash License", "Pexels License"})

_REQUEST_TIMEOUT = 15  # seconds


class ImageSourcer:
    """Copyright-safe image sourcing from free stock photo APIs and AI generation."""

    UNSPLASH_API = "https://api.unsplash.com"
    PEXELS_API = "https://api.pexels.com/v1"

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        unsplash_key: Optional[str] = None,
        pexels_key: Optional[str] = None,
    ) -> None:
        """Load API keys from explicit args or environment variables.

        Both keys are optional.  The sourcer works with any combination
        (both, either, or none -- in which case SVG placeholders are used).

        Args:
            unsplash_key: Unsplash access key.  Falls back to
                ``UNSPLASH_ACCESS_KEY`` env var.
            pexels_key: Pexels API key.  Falls back to
                ``PEXELS_API_KEY`` env var.
        """
        self._unsplash_key: Optional[str] = (
            unsplash_key or os.environ.get("UNSPLASH_ACCESS_KEY")
        )
        self._pexels_key: Optional[str] = (
            pexels_key or os.environ.get("PEXELS_API_KEY")
        )

        if self._unsplash_key:
            logger.info("Unsplash API key loaded.")
        if self._pexels_key:
            logger.info("Pexels API key loaded.")
        if not self._unsplash_key and not self._pexels_key:
            logger.warning(
                "No image API keys configured. "
                "Only SVG placeholders will be available."
            )

    # ------------------------------------------------------------------
    # Unsplash
    # ------------------------------------------------------------------

    def search_unsplash(self, query: str, count: int = 3) -> list[dict]:
        """Search Unsplash for copyright-safe photos.

        Args:
            query: Search term (e.g. ``"machine learning"``).
            count: Maximum number of results (1-30).

        Returns:
            List of image dicts with standardised keys.
            Empty list when no API key is set or the request fails.
        """
        if not self._unsplash_key:
            logger.debug("Unsplash search skipped: no API key.")
            return []

        url = f"{self.UNSPLASH_API}/search/photos"
        params = {
            "query": query,
            "per_page": min(count, 30),
            "orientation": "landscape",
        }
        headers = {"Authorization": f"Client-ID {self._unsplash_key}"}

        try:
            resp = requests.get(
                url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Unsplash API error: %s", exc)
            return []

        results: list[dict] = []
        for photo in resp.json().get("results", []):
            results.append(self._parse_unsplash_photo(photo))
        return results

    @staticmethod
    def _parse_unsplash_photo(photo: dict) -> dict:
        """Convert an Unsplash API photo object to a standardised dict."""
        user = photo.get("user", {})
        urls = photo.get("urls", {})
        return {
            "url": urls.get("regular", ""),
            "thumbnail_url": urls.get("thumb", ""),
            "photographer": user.get("name", "Unknown"),
            "photographer_url": user.get("links", {}).get("html", ""),
            "license": "Unsplash License",
            "download_url": urls.get("full", urls.get("raw", "")),
            "alt_text": photo.get("alt_description") or photo.get("description") or "",
            "platform": "Unsplash",
            "platform_url": "https://unsplash.com",
        }

    # ------------------------------------------------------------------
    # Pexels
    # ------------------------------------------------------------------

    def search_pexels(self, query: str, count: int = 3) -> list[dict]:
        """Search Pexels for copyright-safe photos.

        Args:
            query: Search term.
            count: Maximum number of results (1-80).

        Returns:
            List of image dicts with standardised keys.
            Empty list when no API key is set or the request fails.
        """
        if not self._pexels_key:
            logger.debug("Pexels search skipped: no API key.")
            return []

        url = f"{self.PEXELS_API}/search"
        params = {
            "query": query,
            "per_page": min(count, 80),
            "orientation": "landscape",
        }
        headers = {"Authorization": self._pexels_key}

        try:
            resp = requests.get(
                url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Pexels API error: %s", exc)
            return []

        results: list[dict] = []
        for photo in resp.json().get("photos", []):
            results.append(self._parse_pexels_photo(photo))
        return results

    @staticmethod
    def _parse_pexels_photo(photo: dict) -> dict:
        """Convert a Pexels API photo object to a standardised dict."""
        src = photo.get("src", {})
        return {
            "url": src.get("large", ""),
            "thumbnail_url": src.get("medium", ""),
            "photographer": photo.get("photographer", "Unknown"),
            "photographer_url": photo.get("photographer_url", ""),
            "license": "Pexels License",
            "download_url": src.get("original", ""),
            "alt_text": photo.get("alt") or "",
            "platform": "Pexels",
            "platform_url": "https://www.pexels.com",
        }

    # ------------------------------------------------------------------
    # Combined search
    # ------------------------------------------------------------------

    def find_images(self, query: str, count: int = 3) -> list[dict]:
        """Search Unsplash first, then Pexels, and return combined results.

        Each result includes full attribution information.

        Args:
            query: Search term.
            count: Desired total number of results.

        Returns:
            Combined list of image dicts, up to *count* items.
        """
        images: list[dict] = []

        unsplash_results = self.search_unsplash(query, count=count)
        images.extend(unsplash_results)

        remaining = count - len(images)
        if remaining > 0:
            pexels_results = self.search_pexels(query, count=remaining)
            images.extend(pexels_results)

        if not images:
            logger.info(
                "No images found for query '%s'; generating SVG placeholder.",
                query,
            )
            images.append(self._placeholder_as_image_dict(query))

        # Validate every image has required attribution fields.
        for img in images:
            self._validate_image(img)

        return images[:count]

    # ------------------------------------------------------------------
    # Attribution
    # ------------------------------------------------------------------

    @staticmethod
    def generate_attribution(image: dict) -> str:
        """Generate a Markdown attribution string for an image.

        Format::

            Photo by [Photographer](url) on [Platform](platform_url) - [License]

        Args:
            image: Image dict as returned by search methods.

        Returns:
            Markdown-formatted attribution string.
        """
        photographer = image.get("photographer", "Unknown")
        photographer_url = image.get("photographer_url", "")
        platform = image.get("platform", "Stock Photo")
        platform_url = image.get("platform_url", "")
        license_name = image.get("license", "Unknown License")

        photographer_link = (
            f"[{photographer}]({photographer_url})"
            if photographer_url
            else photographer
        )
        platform_link = (
            f"[{platform}]({platform_url})" if platform_url else platform
        )

        return f"Photo by {photographer_link} on {platform_link} - {license_name}"

    # ------------------------------------------------------------------
    # SVG placeholder
    # ------------------------------------------------------------------

    @staticmethod
    def generate_placeholder_svg(
        text: str,
        width: int = 800,
        height: int = 400,
    ) -> str:
        """Generate a simple SVG placeholder image with centred text.

        Useful as a fallback when no API keys are configured.

        Args:
            text: Text to display in the placeholder.
            width: SVG width in pixels.
            height: SVG height in pixels.

        Returns:
            SVG markup string.
        """
        # Escape basic XML entities in the text.
        safe_text = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
            f'<rect width="100%" height="100%" fill="#e2e8f0"/>'
            f'<text x="50%" y="50%" dominant-baseline="middle" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'font-size="24" fill="#64748b">{safe_text}</text>'
            f"</svg>"
        )

    # ------------------------------------------------------------------
    # Hero & section image selection
    # ------------------------------------------------------------------

    def select_hero_image(self, topic: str) -> dict:
        """Find the best hero image for an article topic.

        Returns the top-ranked image from :meth:`find_images` with
        attribution pre-generated.

        Args:
            topic: Article topic or title.

        Returns:
            Image dict with an ``attribution`` key added.
        """
        images = self.find_images(topic, count=1)
        if not images:
            return self._placeholder_as_image_dict(topic)

        image = images[0]
        image["attribution"] = self.generate_attribution(image)
        return image

    def select_section_images(
        self, topics: list[str], count: int = 3
    ) -> list[dict]:
        """Find images for article section breaks.

        Distributes search queries across topics to get variety.

        Args:
            topics: List of section topic strings.
            count: Total number of images desired.

        Returns:
            List of image dicts, each with ``attribution``.
        """
        images: list[dict] = []
        per_topic = max(1, count // max(len(topics), 1))

        for topic in topics:
            batch = self.find_images(topic, count=per_topic)
            for img in batch:
                img["attribution"] = self.generate_attribution(img)
                images.append(img)
            if len(images) >= count:
                break

        return images[:count]

    # ------------------------------------------------------------------
    # Markdown helpers
    # ------------------------------------------------------------------

    def _build_image_markdown(
        self,
        image: dict,
        caption: str = "",
        width: str = "",
    ) -> str:
        """Build a Markdown image tag with caption and attribution.

        Output format::

            ![alt_text](url)
            *caption -- Photo by Photographer on Platform*

        Args:
            image: Image dict.
            caption: Optional caption text.
            width: Optional width hint (ignored in plain Markdown but
                kept for HTML-capable renderers).

        Returns:
            Markdown string for the image block.
        """
        alt = image.get("alt_text", "")
        url = image.get("url", "")
        attribution = self.generate_attribution(image)

        parts: list[str] = []
        if width:
            parts.append(f'<img src="{url}" alt="{alt}" width="{width}"/>')
        else:
            parts.append(f"![{alt}]({url})")

        caption_parts = [p for p in (caption, attribution) if p]
        if caption_parts:
            parts.append(f"*{' -- '.join(caption_parts)}*")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_image(image: dict) -> None:
        """Warn if required attribution fields are missing.

        Does not raise -- just logs warnings so the pipeline continues.
        """
        license_name = image.get("license", "")
        if license_name and license_name not in _ALLOWED_LICENSES:
            logger.warning(
                "Image license '%s' is not in the allowed set: %s",
                license_name,
                _ALLOWED_LICENSES,
            )

        if not image.get("alt_text"):
            logger.warning(
                "Image from %s is missing alt text.",
                image.get("photographer", "unknown"),
            )

        if not image.get("download_url"):
            logger.warning(
                "Image from %s has no download URL for local storage.",
                image.get("photographer", "unknown"),
            )

    def _placeholder_as_image_dict(self, text: str) -> dict:
        """Wrap an SVG placeholder in the standard image dict format."""
        svg = self.generate_placeholder_svg(text)
        return {
            "url": "",
            "thumbnail_url": "",
            "photographer": "",
            "photographer_url": "",
            "license": "CC0",
            "download_url": "",
            "alt_text": text,
            "platform": "Placeholder",
            "platform_url": "",
            "svg": svg,
        }
