"""Source fetchers: pull recent items from RSS, HN Algolia, Reddit, arXiv.

Each fetcher returns a list of normalised dicts:
    {
      "source": "OpenAI Blog",
      "tier": 1,
      "item_id": "<unique id within source>",
      "title": "...",
      "url": "https://...",
      "published_at": datetime | None,
      "raw_summary": "<abstract or first paragraph, may be empty>",
    }

No paid APIs. All endpoints are free public feeds.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET  # kept for ET.Element type annotations
import defusedxml.ElementTree as _SafeET  # hardened parser (XXE / billion-laughs)
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

# (name, type, url, tier)
SOURCES: list[tuple[str, str, str, int]] = [
    # Official RSS — Anthropic & Meta AI dropped RSS; we compensate by
    # keyword-searching HN for "Anthropic" / "Meta AI" below.
    ("OpenAI", "rss", "https://openai.com/news/rss.xml", 1),
    ("DeepMind", "rss", "https://deepmind.google/blog/rss.xml", 1),
    ("NVIDIA Developer", "rss", "https://developer.nvidia.com/blog/feed/", 1),
    ("HuggingFace", "rss", "https://huggingface.co/blog/feed.xml", 2),
    # HN keyword searches — catches official-lab news even when no RSS exists.
    ("HN · AI", "hn", "https://hn.algolia.com/api/v1/search?tags=story&query=AI&hitsPerPage=25", 2),
    ("HN · Anthropic", "hn", "https://hn.algolia.com/api/v1/search?tags=story&query=Anthropic&hitsPerPage=10", 1),
    ("HN · OpenAI", "hn", "https://hn.algolia.com/api/v1/search?tags=story&query=OpenAI&hitsPerPage=10", 1),
    ("HN · Meta AI", "hn", "https://hn.algolia.com/api/v1/search?tags=story&query=%22Meta+AI%22&hitsPerPage=5", 1),
    # Community feeds.
    ("Reddit r/LocalLLaMA", "reddit", "https://www.reddit.com/r/LocalLLaMA/.rss", 3),
    ("Reddit r/MachineLearning", "reddit", "https://www.reddit.com/r/MachineLearning/.rss", 3),
    ("arXiv cs.AI", "arxiv", "https://export.arxiv.org/rss/cs.AI", 3),
]

# Reject items older than this — widen to 72h so weekend news survives,
# and labs that publish 2-3 times / week still contribute.
_MAX_AGE = timedelta(hours=72)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; ai-catchup/0.1; +personal-use)"
)
_TIMEOUT = 15

# Strip namespace prefixes like "{http://www.w3.org/2005/Atom}entry" → "entry".
_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _findtext(el: ET.Element, names: tuple[str, ...]) -> str:
    """Return text of the first matching child (case-insensitive, ns-stripped)."""
    wanted = {n.lower() for n in names}
    for child in el.iter():
        if _strip_ns(child.tag).lower() in wanted and child.text:
            return child.text.strip()
    return ""


def _findattr(el: ET.Element, names: tuple[str, ...], attr: str) -> str:
    wanted = {n.lower() for n in names}
    for child in el.iter():
        if _strip_ns(child.tag).lower() in wanted:
            v = child.get(attr)
            if v:
                return v.strip()
    return ""


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except ValueError:
            continue
    return None


def _is_fresh(d: datetime | None) -> bool:
    if d is None:
        return True  # keep undated items, dedup will sort it out
    now = datetime.now(timezone.utc)
    return (now - d) < _MAX_AGE


def _fetch(url: str) -> bytes:
    r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.content


def _parse_rss(name: str, tier: int, url: str) -> list[dict[str, Any]]:
    body = _fetch(url)
    root = _SafeET.fromstring(body)
    items: list[dict[str, Any]] = []
    # Both RSS (channel/item) and Atom (entry) — iterate all entry-like nodes.
    for el in root.iter():
        tag = _strip_ns(el.tag).lower()
        if tag not in ("item", "entry"):
            continue
        title = _findtext(el, ("title",))
        link = _findtext(el, ("link",)) or _findattr(el, ("link",), "href")
        guid = (
            _findtext(el, ("guid", "id"))
            or link
            or title
        )
        published = _parse_date(
            _findtext(el, ("pubdate", "published", "updated", "dc:date"))
        )
        summary = (_findtext(el, ("description", "summary", "content")) or "")[:1500]
        if not title or not link:
            continue
        if not _is_fresh(published):
            continue
        items.append(
            {
                "source": name,
                "tier": tier,
                "item_id": guid,
                "title": title,
                "url": link,
                "published_at": published,
                "raw_summary": _strip_html(summary),
            }
        )
    return items


def _parse_hn(name: str, tier: int, url: str) -> list[dict[str, Any]]:
    r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    items: list[dict[str, Any]] = []
    for hit in data.get("hits", []):
        title = hit.get("title") or ""
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        published = _parse_date(hit.get("created_at", ""))
        if not title:
            continue
        if not _is_fresh(published):
            continue
        items.append(
            {
                "source": name,
                "tier": tier,
                "item_id": str(hit.get("objectID")),
                "title": title,
                "url": link,
                "published_at": published,
                "raw_summary": (hit.get("story_text") or "")[:1500],
                "score": hit.get("points"),
            }
        )
    return items


def _strip_html(s: str) -> str:
    """Cheap HTML strip — not security-grade, just for prompt sanity."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def fetch_all() -> list[dict[str, Any]]:
    """Fetch every configured source and return a flat item list.

    Per-source failures are logged and skipped so one dead feed doesn't
    take down the whole catchup.
    """
    out: list[dict[str, Any]] = []
    for name, kind, url, tier in SOURCES:
        try:
            if kind == "rss" or kind == "reddit" or kind == "arxiv":
                items = _parse_rss(name, tier, url)
            elif kind == "hn":
                items = _parse_hn(name, tier, url)
            else:
                logger.warning("Unknown source kind: %s", kind)
                continue
            logger.info("[%s] %d items", name, len(items))
            out.extend(items)
        except Exception as exc:  # noqa: BLE001 - keep loop alive
            logger.warning("[%s] fetch failed: %s", name, exc)
    return out
