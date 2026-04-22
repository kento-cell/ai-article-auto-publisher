"""A/B-test flag loader.

Reads ``config/experiments.yaml`` once per process and returns flag
values via :func:`is_enabled`. All self-learning improvements funnel
through this module so they can be individually toggled without code
edits — useful for A/B measurement (run a pipeline with a flag on,
run again with it off, compare scores/views).

Missing flags default to ``True`` to preserve the current
post-2026-04-22 behaviour. Unknown groups return empty dicts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "experiments.yaml"
_CACHE: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _CONFIG_PATH.exists():
        _CACHE = {}
        return _CACHE
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _CACHE = yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("experiments.yaml load failed: %s — defaulting all flags on", exc)
        _CACHE = {}
    return _CACHE


def is_enabled(flag: str, default: bool = True) -> bool:
    """Return whether *flag* (``group.feature``) is enabled.

    Defaults to *default* (True) when the flag is absent so
    improvements added without touching the yaml still take effect.
    """
    if "." not in flag:
        return default
    group, feature = flag.split(".", 1)
    cfg = _load()
    section = cfg.get(group) or {}
    if not isinstance(section, dict):
        return default
    value = section.get(feature, default)
    return bool(value)


def record_variant(article: dict, flags: list[str]) -> None:
    """Write which flags were on for this article onto the article
    dict under ``experiment_variant``. Used for later A/B analysis.
    """
    variant = {flag: is_enabled(flag) for flag in flags}
    article.setdefault("experiment_variant", {}).update(variant)
