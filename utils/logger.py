"""Structured logging utility with file rotation and console output.

Provides a configured logger that writes UTF-8 encoded output to both
the console and a rotating log file under the ``logs/`` directory.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per log file
_BACKUP_COUNT = 3
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str = "ai_article",
    level: int = logging.INFO,
    log_dir: Path | None = None,
) -> logging.Logger:
    """Create and return a logger with console and rotating-file handlers.

    Args:
        name: Logger name. Defaults to ``"ai_article"``.
        level: Minimum log level. Defaults to ``logging.INFO``.
        log_dir: Directory for log files. Defaults to ``<project>/logs/``.

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers on repeated calls.
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # --- Console handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # --- File handler (rotating, UTF-8) ---
    target_dir = log_dir or _DEFAULT_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / f"{name}.log"

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.debug("Logger '%s' initialised (file=%s)", name, log_file)
    return logger


def get_logger(name: str = "ai_article") -> logging.Logger:
    """Return an existing logger or create one with default settings.

    This is a convenience wrapper so callers do not need to import
    :func:`setup_logger` directly.

    Args:
        name: Logger name.

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
