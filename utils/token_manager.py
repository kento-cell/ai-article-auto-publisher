"""Token usage tracking with weekly budgets and persistence.

Tracks cumulative token consumption per ISO-week, persists data to a
JSON file, and raises alerts when usage approaches the configured limit.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.logger import get_logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WEEKLY_LIMIT: int = 2_000_000
_BUFFER_RATIO: float = 0.50  # 50 % buffer -> effective cap = 3 M
_ALERT_THRESHOLD: float = 0.80  # warn at 80 % of effective cap
_DEFAULT_DATA_PATH: Path = (
    Path(__file__).resolve().parent.parent / "data" / "token_usage.json"
)


def _effective_limit() -> int:
    """Return the weekly limit including the 50 % buffer."""
    return int(_WEEKLY_LIMIT * (1 + _BUFFER_RATIO))


def _current_week_key() -> str:
    """Return an ISO-week string like ``'2026-W15'``."""
    now = datetime.now(tz=timezone.utc)
    return f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"


class TokenManager:
    """Manage weekly token budgets with JSON-file persistence.

    Args:
        data_path: Path to the JSON file storing usage history.
    """

    def __init__(self, data_path: Path | None = None) -> None:
        self._path: Path = data_path or _DEFAULT_DATA_PATH
        self._logger: logging.Logger = get_logger("token_manager")
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """Load usage data from disk, returning empty structure on failure."""
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                self._logger.warning("Failed to load token data: %s", exc)
        return {"weeks": {}}

    def _save(self) -> None:
        """Write current usage data to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_usage(self, tokens: int) -> None:
        """Add *tokens* to the current week's tally and persist.

        Args:
            tokens: Number of tokens consumed.

        Raises:
            ValueError: If *tokens* is negative.
        """
        if tokens < 0:
            raise ValueError("tokens must be non-negative")

        week = _current_week_key()
        weeks: dict[str, int] = self._data.setdefault("weeks", {})
        weeks[week] = weeks.get(week, 0) + tokens
        self._save()

        used = weeks[week]
        limit = _effective_limit()
        if used >= int(limit * _ALERT_THRESHOLD):
            self._logger.warning(
                "Token alert: %s used %d / %d (%.0f%%)",
                week,
                used,
                limit,
                used / limit * 100,
            )

    def get_remaining(self) -> int:
        """Return the number of tokens still available this week."""
        week = _current_week_key()
        used = self._data.get("weeks", {}).get(week, 0)
        return max(0, _effective_limit() - used)

    def is_within_budget(self) -> bool:
        """Return ``True`` if this week's usage is under the effective cap."""
        return self.get_remaining() > 0

    def reset_weekly(self, week: str | None = None) -> None:
        """Reset the counter for a given week (defaults to current week).

        Args:
            week: ISO-week key such as ``'2026-W15'``.
                  Defaults to the current week.
        """
        target = week or _current_week_key()
        self._data.setdefault("weeks", {})[target] = 0
        self._save()
        self._logger.info("Token usage reset for %s", target)
