"""SQLite telemetry store for RAG / generation observability.

Schema designed 2026-05-11 — see docs/sessions/archive/_legacy/20260511_db_schema_design.md.
4 tables, all append-only:
- engagement_log    : public-article engagement (♥ / 💬 / views)
- regen_history     : per-attempt scoring history for each article
- ab_experiments    : A/B test variant assignments + outcomes
- generation_cost   : LLM / image-API cost trace per event

Design notes
- Single file at data/telemetry.sqlite3 (gitignored). Small (<10MB
  expected for the first year).
- Uses stdlib ``sqlite3`` only — no new dependencies.
- All writes go through ``record_*`` helpers that swallow exceptions
  so a broken DB never breaks the generation / publish pipelines.
- ``init_db()`` is idempotent (CREATE TABLE IF NOT EXISTS); safe to
  call at every process start.
- Foreign key constraints are declared but NOT enforced (sqlite
  default), since article_id may be created before the JSON file
  exists on disk.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_DB_PATH = _REPO / "data" / "telemetry.sqlite3"


_SCHEMA = [
    # engagement_log -----------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS engagement_log (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      article_id      TEXT    NOT NULL,
      platform        TEXT    NOT NULL,
      url             TEXT    NOT NULL,
      measured_at     TEXT    NOT NULL,
      likes           INTEGER DEFAULT 0,
      comments        INTEGER DEFAULT 0,
      views           INTEGER,
      engagement_score REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_engagement_article ON engagement_log(article_id)",
    "CREATE INDEX IF NOT EXISTS idx_engagement_time    ON engagement_log(measured_at)",
    # regen_history ------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS regen_history (
      id                INTEGER PRIMARY KEY AUTOINCREMENT,
      article_id        TEXT    NOT NULL,
      attempt           INTEGER NOT NULL,
      timestamp         TEXT    NOT NULL,
      objective_grade   TEXT,
      subjective_grade  TEXT,
      overall_grade     TEXT,
      numeric_score     REAL,
      trigger_reason    TEXT,
      feedback_summary  TEXT,
      word_count        INTEGER,
      blocking_issues   TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_regen_article  ON regen_history(article_id)",
    "CREATE INDEX IF NOT EXISTS idx_regen_attempt  ON regen_history(article_id, attempt)",
    # ab_experiments -----------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS ab_experiments (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      experiment_id   TEXT    NOT NULL,
      variant         TEXT    NOT NULL,
      article_id      TEXT    NOT NULL,
      generated_at    TEXT    NOT NULL,
      objective_grade TEXT,
      subjective_grade TEXT,
      overall_grade   TEXT,
      numeric_score   REAL,
      word_count      INTEGER,
      hallucination_warnings_count INTEGER,
      rag_block_chars INTEGER,
      notes           TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ab_exp     ON ab_experiments(experiment_id, variant)",
    "CREATE INDEX IF NOT EXISTS idx_ab_article ON ab_experiments(article_id)",
    # generation_cost ----------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS generation_cost (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      article_id      TEXT,
      event_type      TEXT    NOT NULL,
      model           TEXT,
      timestamp       TEXT    NOT NULL,
      duration_ms     INTEGER,
      input_tokens    INTEGER,
      output_tokens   INTEGER,
      cost_usd        REAL,
      notes           TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cost_article ON generation_cost(article_id)",
    "CREATE INDEX IF NOT EXISTS idx_cost_event   ON generation_cost(event_type, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_cost_time    ON generation_cost(timestamp)",
]


# ---------------------------------------------------------------------------
# Connection / init
# ---------------------------------------------------------------------------


def _ensure_parent() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Context-managed connection. Auto-commits on exit (no transaction
    nesting needed for our append-only writes)."""
    _ensure_parent()
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables + indexes if missing. Idempotent."""
    try:
        with connect() as conn:
            cur = conn.cursor()
            for stmt in _SCHEMA:
                cur.execute(stmt)
    except sqlite3.Error as exc:
        logger.warning("telemetry init failed: %s", exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Recorders (silent on failure)
# ---------------------------------------------------------------------------


def record_engagement(
    article_id: str,
    platform: str,
    url: str,
    likes: int = 0,
    comments: int = 0,
    views: int | None = None,
    measured_at: str | None = None,
) -> None:
    """Append one engagement measurement."""
    score = likes + 0.5 * comments + 0.1 * (views or 0)
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO engagement_log "
                "(article_id, platform, url, measured_at, likes, comments, views, engagement_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article_id, platform, url,
                    measured_at or _now_iso(),
                    likes, comments, views, score,
                ),
            )
    except sqlite3.Error as exc:
        logger.debug("engagement record failed: %s", exc)


def record_regen(
    article_id: str,
    attempt: int,
    grades: dict | None,
    trigger_reason: str,
    word_count: int | None,
    feedback_summary: str = "",
    blocking_issues: list[str] | None = None,
) -> None:
    """Append one regen attempt record (attempt=0 for initial)."""
    g = grades or {}
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO regen_history "
                "(article_id, attempt, timestamp, objective_grade, "
                "subjective_grade, overall_grade, numeric_score, "
                "trigger_reason, feedback_summary, word_count, blocking_issues) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article_id, attempt, _now_iso(),
                    g.get("objective_grade"),
                    g.get("subjective_grade"),
                    g.get("overall_grade"),
                    g.get("numeric_score"),
                    trigger_reason,
                    feedback_summary[:200] if feedback_summary else None,
                    word_count,
                    json.dumps(blocking_issues or [], ensure_ascii=False),
                ),
            )
    except sqlite3.Error as exc:
        logger.debug("regen record failed: %s", exc)


def record_ab(
    experiment_id: str,
    variant: str,
    article_id: str,
    grades: dict | None = None,
    word_count: int | None = None,
    hallucination_warnings_count: int = 0,
    rag_block_chars: int = 0,
    notes: str = "",
) -> None:
    """Append one A/B experiment outcome row."""
    g = grades or {}
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO ab_experiments "
                "(experiment_id, variant, article_id, generated_at, "
                "objective_grade, subjective_grade, overall_grade, "
                "numeric_score, word_count, hallucination_warnings_count, "
                "rag_block_chars, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    experiment_id, variant, article_id, _now_iso(),
                    g.get("objective_grade"),
                    g.get("subjective_grade"),
                    g.get("overall_grade"),
                    g.get("numeric_score"),
                    word_count,
                    hallucination_warnings_count,
                    rag_block_chars,
                    notes[:500] if notes else None,
                ),
            )
    except sqlite3.Error as exc:
        logger.debug("ab_experiments record failed: %s", exc)


def record_cost(
    event_type: str,
    article_id: str | None = None,
    model: str | None = None,
    duration_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    notes: str = "",
) -> None:
    """Append one cost-trace event."""
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO generation_cost "
                "(article_id, event_type, model, timestamp, duration_ms, "
                "input_tokens, output_tokens, cost_usd, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article_id, event_type, model, _now_iso(),
                    duration_ms, input_tokens, output_tokens, cost_usd,
                    notes[:300] if notes else None,
                ),
            )
    except sqlite3.Error as exc:
        logger.debug("cost record failed: %s", exc)


# ---------------------------------------------------------------------------
# Read helpers (for telemetry_report.py etc.)
# ---------------------------------------------------------------------------


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run an ad-hoc SELECT and return list of dicts."""
    try:
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as exc:
        logger.warning("telemetry query failed: %s", exc)
        return []


def stats() -> dict[str, int]:
    """Quick row counts per table — useful for health checks."""
    tables = ("engagement_log", "regen_history", "ab_experiments", "generation_cost")
    out: dict[str, int] = {}
    for t in tables:
        rows = query(f"SELECT COUNT(*) AS n FROM {t}")
        out[t] = rows[0]["n"] if rows else 0
    return out
