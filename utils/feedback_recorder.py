"""Lightweight feedback recording for article performance tracking.

Records basic article metrics (PV, likes, etc.) for future analysis.
v1.0: recording only, no automated analysis.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "feedback.json"


class FeedbackRecorder:
    """Record article performance metrics for future analysis.

    v1.0 scope: store metrics only. Automated analysis is v1.1+.
    """

    def __init__(self, data_path: Path | None = None) -> None:
        self._path = data_path or _DEFAULT_PATH
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load feedback data: %s", e)
        return {"articles": []}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def record_publish(
        self,
        platform: str,
        title: str,
        url: str,
        quality_score: float,
        structure_type: str = "standard",
        price: int = 0,
    ) -> None:
        """Record that an article was published."""
        entry = {
            "platform": platform,
            "title": title,
            "url": url,
            "quality_score": quality_score,
            "structure_type": structure_type,
            "price": price,
            "published_at": datetime.now(tz=timezone.utc).isoformat(),
            "metrics": {},  # placeholder for future PV/likes tracking
        }
        self._data["articles"].append(entry)
        self._save()
        logger.info("Recorded publish: %s on %s", title[:30], platform)

    def record_metrics(
        self, url: str, metrics: dict[str, Any]
    ) -> None:
        """Update metrics for a previously recorded article (manual input for v1.0)."""
        for article in self._data["articles"]:
            if article["url"] == url:
                article["metrics"].update(metrics)
                article["metrics_updated_at"] = datetime.now(tz=timezone.utc).isoformat()
                self._save()
                logger.info("Updated metrics for: %s", url)
                return
        logger.warning("Article not found for metrics update: %s", url)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all recorded articles."""
        return self._data.get("articles", [])

    def get_structure_distribution(self) -> dict[str, int]:
        """Return count of articles by structure type."""
        dist: dict[str, int] = {}
        for article in self._data.get("articles", []):
            st = article.get("structure_type", "unknown")
            dist[st] = dist.get(st, 0) + 1
        return dist
