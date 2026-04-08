"""Track our published articles' performance over time."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TRACK_FILE = _REPO_ROOT / "data" / "my_articles.json"


class ArticleTracker:
    """Track published articles and their metrics."""

    def __init__(self) -> None:
        _TRACK_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if _TRACK_FILE.exists():
            try:
                return json.loads(_TRACK_FILE.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save(self, data: list[dict]) -> None:
        _TRACK_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def register_published(
        self, platform: str, url: str, title: str, generated_at: str = ""
    ) -> None:
        """Register a newly published article."""
        articles = self._load()
        if any(a.get("url") == url for a in articles):
            return  # Already registered
        articles.append({
            "platform": platform,
            "url": url,
            "title": title,
            "generated_at": generated_at or datetime.now().isoformat(),
            "registered_at": datetime.now().isoformat(),
            "metrics_history": [],
        })
        self._save(articles)
        logger.info("Tracked: %s", title[:40])

    def update_metrics(self, url: str, scraper) -> dict | None:
        """Fetch current metrics from URL and append to history."""
        articles = self._load()
        target = None
        for a in articles:
            if a.get("url") == url:
                target = a
                break
        if not target:
            return None

        try:
            detail = scraper.fetch_article_detail(url)
            metric = {
                "fetched_at": datetime.now().isoformat(),
                "word_count": detail.get("word_count", 0),
                "h2_count": detail.get("h2_count", 0),
                "image_count": detail.get("image_count", 0),
            }
            target.setdefault("metrics_history", []).append(metric)
            self._save(articles)
            return metric
        except Exception as e:
            logger.warning("Metric update failed for %s: %s", url, e)
            return None

    def get_top_my_articles(self, n: int = 10) -> list[dict]:
        """Return our best-performing articles by latest metrics."""
        articles = self._load()
        # Sort by latest known engagement (placeholder: word_count for now)
        scored = []
        for a in articles:
            history = a.get("metrics_history", [])
            score = history[-1].get("word_count", 0) if history else 0
            scored.append((score, a))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [a for _, a in scored[:n]]

    def get_performance_summary(self) -> dict[str, Any]:
        """Aggregate stats across all tracked articles."""
        articles = self._load()
        if not articles:
            return {"total": 0}
        platforms = {}
        for a in articles:
            p = a.get("platform", "unknown")
            platforms[p] = platforms.get(p, 0) + 1
        return {
            "total": len(articles),
            "platforms": platforms,
            "tracked_since": min(
                (a.get("registered_at", "") for a in articles), default=""
            ),
        }
