"""Automated cleanup of stale data to prevent disk bloat.

Runs as a post-generate hook or standalone. Removes:
- Old log files (> 7 days)
- Old regeneration discussion logs (> 14 days)
- Trimmed seen_urls / generated_sources / rejected_posted to cap size
- Old cover images (> 30 days)
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def cleanup_all() -> dict[str, int]:
    """Run all cleanup tasks. Returns counts of items removed."""
    results = {}
    results["logs"] = _cleanup_old_files(PROJECT_ROOT / "logs", days=7, pattern="*.log")
    results["regen_logs"] = _cleanup_old_files(
        PROJECT_ROOT / "logs" / "regeneration", days=14, pattern="*.md"
    )
    results["cover_images"] = _cleanup_old_files(
        PROJECT_ROOT / "docs" / "images" / "covers", days=30, pattern="*.png"
    )
    results["data_images"] = _cleanup_old_files(
        PROJECT_ROOT / "data" / "images", days=30, pattern="*.png"
    )
    results["json_trimmed"] = _trim_json_files()

    total = sum(results.values())
    if total > 0:
        logger.info("クリーンアップ完了: %s", results)
    return results


def _cleanup_old_files(directory: Path, days: int, pattern: str) -> int:
    """Delete files older than `days` matching `pattern`."""
    if not directory.exists():
        return 0

    cutoff = time.time() - (days * 86400)
    removed = 0
    for f in directory.glob(pattern):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def _trim_json_files() -> int:
    """Trim JSON tracking files to prevent unbounded growth."""
    trimmed = 0

    for filename, max_size, keep_size in [
        ("data/seen_urls.json", 10000, 5000),
        ("data/generated_sources.json", 500, 250),
        ("data/rejected_posted.json", 200, 100),
    ]:
        path = PROJECT_ROOT / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) > max_size:
                data = data[-keep_size:]
                path.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
                trimmed += 1
                logger.info("Trimmed %s: %d -> %d", filename, len(data) + (max_size - keep_size), keep_size)
        except Exception:
            pass

    return trimmed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = cleanup_all()
    print(f"Cleanup results: {results}")
