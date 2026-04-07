"""Local file-based article content storage.

Saves generated article content to JSON files so they persist between
--generate (create) and --publish (retrieve) runs.

Storage: data/articles/{article_id}.json
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "articles"


class ArticleStore:
    """Persist article content between pipeline runs."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._dir = store_dir or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, article_id: str, data: dict) -> Path:
        """Save article data to a JSON file.

        Args:
            article_id: Unique identifier (slug).
            data: Dict containing at minimum: title, content, platform, scores.

        Returns:
            Path to the saved file.
        """
        path = self._dir / f"{self._safe_filename(article_id)}.json"
        payload = {
            **data,
            "article_id": article_id,
            "saved_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        # Don't serialize non-serializable objects
        for key in list(payload.keys()):
            try:
                json.dumps(payload[key])
            except (TypeError, ValueError):
                payload[key] = str(payload[key])

        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Article saved: %s", path)
        return path

    def load(self, article_id: str) -> Optional[dict]:
        """Load article data by ID.

        Returns:
            Article dict, or None if not found.
        """
        path = self._dir / f"{self._safe_filename(article_id)}.json"
        if not path.exists():
            logger.warning("Article not found: %s", article_id)
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load article %s: %s", article_id, e)
            return None

    def delete(self, article_id: str) -> bool:
        """Delete a saved article."""
        path = self._dir / f"{self._safe_filename(article_id)}.json"
        if path.exists():
            path.unlink()
            logger.info("Article deleted: %s", article_id)
            return True
        return False

    def list_all(self) -> list[str]:
        """List all saved article IDs."""
        return [p.stem for p in self._dir.glob("*.json")]

    @staticmethod
    def _safe_filename(article_id: str) -> str:
        """Convert article_id to a safe filename."""
        safe = re.sub(r'[^\w\-]', '_', article_id)
        return safe[:100]
