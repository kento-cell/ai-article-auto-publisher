"""Google Places API (v1) verifier for store/spot hallucination prevention.

Used by the note generation pipeline to verify that stores mentioned in
LLM-generated articles actually exist, and to replace hallucinated
factual fields (address, hours, price level, website, phone) with
canonical data returned by Google Places.

LLM writes stores in a placeholder template with subjective fields only
(一言おすすめ / 使用用途). This module parses the template, calls the
Places Text Search endpoint, and either fills the placeholders with
verified data or drops the entire store block if no match is found.

Requires env var: GOOGLE_PLACES_API_KEY
Quota: Places API (New) — $17 / 1000 Text Search, $200/mo free credit.
"""

import logging
import os
import re
import urllib.parse
from typing import Any

import requests

logger = logging.getLogger(__name__)

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.priceLevel",
    "places.rating",
    "places.userRatingCount",
    "places.websiteUri",
    "places.regularOpeningHours",
    "places.googleMapsUri",
    "places.nationalPhoneNumber",
    "places.types",
    "places.businessStatus",
])

# Block types that indicate chain / non-independent shops.
_CHAIN_TYPE_HINTS = {
    "fast_food_restaurant", "convenience_store", "gas_station",
    "supermarket", "department_store", "shopping_mall",
}

_PRICE_LEVEL_JA = {
    "PRICE_LEVEL_FREE": "無料",
    "PRICE_LEVEL_INEXPENSIVE": "〜¥1,000",
    "PRICE_LEVEL_MODERATE": "¥1,000〜¥3,000",
    "PRICE_LEVEL_EXPENSIVE": "¥3,000〜¥7,000",
    "PRICE_LEVEL_VERY_EXPENSIVE": "¥7,000〜",
}

# The LLM is instructed to wrap every verifiable store in explicit
# HTML-comment sentinels so this module never guesses which H3 is a
# store vs. a generic section heading. Example:
#
#   <!-- STORE_BLOCK_START -->
#   ### 店名
#   - 一言おすすめ: ...
#   - 使用用途: ...
#   <!-- STORE_BLOCK_END -->
#
_STORE_BLOCK_START = "<!-- STORE_BLOCK_START -->"
_STORE_BLOCK_END = "<!-- STORE_BLOCK_END -->"

# LLMs (especially small local models) often mangle HTML comment
# markers — dropping the leading/trailing comment delimiters or
# converting them to different punctuation. Match any line whose
# normalised form ends with the core token.
_START_TOKEN_RE = re.compile(r"STORE_BLOCK_START")
_END_TOKEN_RE = re.compile(r"STORE_BLOCK_END")


def _is_start_marker(line: str) -> bool:
    return bool(_START_TOKEN_RE.search(line))


def _is_end_marker(line: str) -> bool:
    return bool(_END_TOKEN_RE.search(line))

# Line prefixes that indicate LLM-authored factual claims. Always
# stripped — even on fail-open paths — to prevent hallucinated
# addresses / hours / phones from reaching readers.
_FACTUAL_PREFIXES: tuple[str, ...] = (
    "住所", "営業", "定休", "予算", "価格", "電話", "公式", "マップ",
    "アクセス", "最寄", "📍", "⏰", "💴", "🔗", "🗺", "☎", "📞",
)


def _find_block_end(lines: list[str], start: int) -> int:
    """Return the index of the matching ``STORE_BLOCK_END`` marker.

    If no closing marker is found, returns the end of *lines*.
    """
    for j in range(start, len(lines)):
        if _is_end_marker(lines[j]):
            return j
    return len(lines)


class PlacesVerifier:
    """Verify and enrich store mentions via Google Places API (v1).

    Args:
        api_key: Google Places API key. Falls back to
            ``GOOGLE_PLACES_API_KEY`` env var.
        language_code: ISO language code for responses (default ``ja``).
        region_code: ISO region code biasing results (default ``JP``).
        request_timeout: HTTP timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        language_code: str = "ja",
        region_code: str = "JP",
        request_timeout: int = 15,
    ) -> None:
        self.api_key = api_key or os.getenv("GOOGLE_PLACES_API_KEY")
        self.language_code = language_code
        self.region_code = region_code
        self.request_timeout = request_timeout

    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return bool(self.api_key)

    def find_place(
        self, name: str, area_hint: str = ""
    ) -> dict[str, Any] | None:
        """Run a Text Search and return the best match, or ``None``.

        Args:
            name: Store / spot display name.
            area_hint: Optional locality hint (e.g. ``"下北沢"``) to
                disambiguate same-named shops.
        """
        if not self.is_available():
            logger.warning("GOOGLE_PLACES_API_KEY not set — verification disabled")
            return None

        query = f"{name} {area_hint}".strip()
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": _FIELD_MASK,
        }
        payload = {
            "textQuery": query,
            "languageCode": self.language_code,
            "regionCode": self.region_code,
            "maxResultCount": 3,
        }
        try:
            r = requests.post(
                PLACES_TEXT_SEARCH_URL,
                headers=headers,
                json=payload,
                timeout=self.request_timeout,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            logger.warning("Places API request failed for %r: %s", query, e)
            return None

        data = r.json() or {}
        places = data.get("places") or []
        if not places:
            return None

        # Pick the first OPERATIONAL result.
        for p in places:
            if p.get("businessStatus", "OPERATIONAL") == "OPERATIONAL":
                return p
        return places[0]

    # ------------------------------------------------------------------

    def verify_and_fill(
        self, content: str, area_hint: str = ""
    ) -> tuple[str, dict[str, int]]:
        """Process *content*, filling verified stores and dropping unverified.

        Uses an explicit line-based parser keyed on the
        ``<!-- STORE_BLOCK_START -->`` / ``<!-- STORE_BLOCK_END -->``
        sentinels emitted by the LLM. No sentinels → no-op (safe for
        non-locality articles).

        Fail-closed: if the API key is missing or a block's API call
        fails, the block's LLM-written factual lines are still
        scrubbed so hallucinated addresses/hours/phones cannot leak.

        Returns:
            Tuple of ``(new_content, stats)`` with ``verified`` /
            ``dropped`` / ``chain_filtered`` / ``scrubbed`` counts.
        """
        stats = {
            "verified": 0, "dropped": 0,
            "chain_filtered": 0, "scrubbed": 0,
        }
        if not _START_TOKEN_RE.search(content):
            # No sentinel blocks — untouched.
            return content, stats

        api_available = self.is_available()
        if not api_available:
            logger.warning(
                "Places API key missing — falling back to fact-strip only."
            )

        lines = content.splitlines()
        out: list[str] = []
        i = 0
        while i < len(lines):
            if _is_start_marker(lines[i]):
                end = _find_block_end(lines, i + 1)
                block_lines = lines[i + 1 : end]
                rendered = self._process_block(
                    block_lines, area_hint, stats, api_available
                )
                if rendered is not None:
                    out.extend(rendered.splitlines())
                # Skip past the END marker.
                i = end + 1
                continue
            out.append(lines[i])
            i += 1

        new_content = "\n".join(out)
        new_content = re.sub(r"\n{4,}", "\n\n\n", new_content)
        return new_content, stats

    def _process_block(
        self,
        block_lines: list[str],
        area_hint: str,
        stats: dict[str, int],
        api_available: bool,
    ) -> str | None:
        """Return the replacement for one store block, or ``None`` to drop it."""
        name_raw = ""
        body_start = 0
        for idx, line in enumerate(block_lines):
            stripped = line.lstrip()
            if stripped.startswith("###"):
                name_raw = stripped.lstrip("#").strip()
                body_start = idx + 1
                break
        if not name_raw:
            return None

        body_lines = block_lines[body_start:]
        clean_name = re.sub(
            r"^[【\[]?\s*\d+\s*[位．.、)】\]]?\s*", "", name_raw
        ).strip()
        if len(clean_name) < 2:
            return None

        place = self.find_place(clean_name, area_hint) if api_available else None
        if place is None:
            # Fail-closed on both unknown-to-API and no-API paths: we
            # do NOT publish unverified stores because doing so is the
            # entire hallucination attack surface we're closing.
            logger.info("Places unverified, dropping: %r", clean_name)
            stats["dropped"] += 1
            stats["scrubbed"] += 1
            return None

        if self._looks_like_chain(place):
            logger.info("Places chain-like, dropping: %r", clean_name)
            stats["chain_filtered"] += 1
            return None

        stats["verified"] += 1
        return self._render_verified_block(name_raw, "\n".join(body_lines), place)

    # ------------------------------------------------------------------

    @staticmethod
    def _is_section_heading(text: str) -> bool:
        meta_words = (
            "まとめ", "はじめに", "おわりに", "結論", "参考文献",
            "目次", "注意", "免責", "エリア別", "ジャンル別",
            "ランキング", "一覧", "比較", "選び方",
        )
        return any(w in text for w in meta_words)

    @staticmethod
    def _looks_like_chain(place: dict[str, Any]) -> bool:
        types = set(place.get("types") or [])
        return bool(types & _CHAIN_TYPE_HINTS)

    def _render_verified_block(
        self, heading: str, llm_body: str, place: dict[str, Any]
    ) -> str:
        """Keep subjective LLM lines, replace factual ones with API data."""
        display = (place.get("displayName") or {}).get("text") or heading
        address = place.get("formattedAddress") or "住所情報なし"
        maps_uri = place.get("googleMapsUri") or self._fallback_maps_url(
            display, address
        )
        website = place.get("websiteUri") or ""
        phone = place.get("nationalPhoneNumber") or ""
        price_level = place.get("priceLevel") or ""
        price_ja = _PRICE_LEVEL_JA.get(price_level, "価格情報なし")
        rating = place.get("rating")
        rating_count = place.get("userRatingCount")
        rating_str = (
            f"⭐ {rating}（{rating_count}件）"
            if rating and rating_count else ""
        )

        hours = self._format_hours(place.get("regularOpeningHours"))

        # Keep only subjective bullets from the LLM output — strip any
        # factual lines it may have written (they are the hallucination
        # risk we are neutralising).
        subjective_lines: list[str] = []
        for line in llm_body.splitlines():
            stripped = line.lstrip("-・* ").strip()
            if not stripped:
                continue
            if any(stripped.startswith(p) for p in _FACTUAL_PREFIXES):
                continue
            subjective_lines.append(line.rstrip())

        parts = [f"### {display}", ""]
        parts.extend(subjective_lines)
        if subjective_lines:
            parts.append("")
        parts.append("**検証済み情報（Google Maps）**")
        parts.append(f"- 📍 住所: {address}")
        if hours:
            parts.append(f"- ⏰ 営業時間: {hours}")
        parts.append(f"- 💴 価格帯目安: {price_ja}")
        if rating_str:
            parts.append(f"- {rating_str}")
        if phone:
            parts.append(f"- ☎ 電話: {phone}")
        if website:
            parts.append(f"- 🔗 公式サイト: {website}")
        parts.append(f"- 🗺️ Googleマップ: {maps_uri}")
        parts.append("")
        return "\n".join(parts)

    @staticmethod
    def _format_hours(hours_obj: dict[str, Any] | None) -> str:
        if not hours_obj:
            return ""
        descs = hours_obj.get("weekdayDescriptions") or []
        if not descs:
            return ""
        return " / ".join(descs)

    @staticmethod
    def _fallback_maps_url(name: str, address: str) -> str:
        q = urllib.parse.quote_plus(f"{name} {address}")
        return f"https://www.google.com/maps/search/?api=1&query={q}"
