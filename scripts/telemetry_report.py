"""Aggregate telemetry SQLite into human-readable + Sheets-pushable report.

Sprint 6-E (2026-05-11). Reads from data/telemetry.sqlite3 and writes
a daily summary markdown to docs/knowledge/telemetry_<YYYY-MM-DD>.md.
Optional --push-sheets uploads the same summary to a Sheets tab named
"Telemetry" so the operator can glance at it from anywhere.

Sections produced
1. Top engagement (last 30 days)
2. Grade distribution + regen retry rate (last 30 days)
3. A/B experiments leaderboard (per experiment_id)
4. Cost breakdown by event_type (last 30 days, total + per-article)

Run::

    py scripts/telemetry_report.py
    py scripts/telemetry_report.py --push-sheets
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.telemetry_db import query, init_db, stats  # noqa: E402


def _format_md(report: dict) -> str:
    lines = [
        f"# Telemetry report — {report['generated_at'][:10]}",
        "",
        "## Table row counts (lifetime)",
        "",
        "| Table | Rows |",
        "|---|---|",
    ]
    for k, v in report["stats"].items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # Engagement leaderboard
    lines.append("## Top engagement — last 30 days")
    lines.append("")
    if report["top_engagement"]:
        lines.append("| Article | Likes | Comments | Score | Last measured |")
        lines.append("|---|---|---|---|---|")
        for row in report["top_engagement"]:
            lines.append(
                f"| {row['article_id'][:50]} | {row['likes']} | "
                f"{row['comments']} | {row['engagement_score']:.1f} | "
                f"{row['last_measured'][:10]} |"
            )
    else:
        lines.append("_(no engagement rows in window)_")
    lines.append("")

    # Grade distribution
    lines.append("## Grade distribution — last 30 days (initial attempts only)")
    lines.append("")
    if report["grade_distribution"]:
        lines.append("| Grade | Count | % |")
        lines.append("|---|---|---|")
        total = sum(r["n"] for r in report["grade_distribution"])
        for r in report["grade_distribution"]:
            pct = (r["n"] / total * 100) if total else 0
            lines.append(
                f"| {r['overall_grade'] or '(none)'} | {r['n']} | "
                f"{pct:.1f}% |"
            )
    else:
        lines.append("_(no regen_history rows yet — wire-in pending)_")
    lines.append("")

    # Regen rate
    lines.append("## Regen retry rate — last 30 days")
    lines.append("")
    rr = report["regen_rate"]
    if rr["total_articles"]:
        lines.append(
            f"- Articles scored: {rr['total_articles']}"
        )
        lines.append(
            f"- Articles that needed a regen retry: {rr['articles_with_retry']} "
            f"({rr['retry_pct']:.1f}%)"
        )
    else:
        lines.append("_(no regen_history rows yet)_")
    lines.append("")

    # A/B experiments
    lines.append("## A/B experiments leaderboard")
    lines.append("")
    if report["ab_experiments"]:
        lines.append(
            "| Experiment | Variant | n | avg score | A-rate |"
        )
        lines.append("|---|---|---|---|---|")
        for r in report["ab_experiments"]:
            lines.append(
                f"| {r['experiment_id']} | {r['variant']} | {r['n']} | "
                f"{r['avg_score']:.1f} | {r['a_rate']:.1f}% |"
            )
    else:
        lines.append("_(no ab_experiments rows yet — wire-in pending)_")
    lines.append("")

    # Cost
    lines.append("## Generation cost — last 30 days")
    lines.append("")
    if report["cost_summary"]:
        lines.append("| Event | n | total ms | total tokens (in+out) | est USD |")
        lines.append("|---|---|---|---|---|")
        for r in report["cost_summary"]:
            tok = (r.get("in_tok") or 0) + (r.get("out_tok") or 0)
            usd = r.get("cost_usd") or 0.0
            lines.append(
                f"| {r['event_type']} | {r['n']} | "
                f"{int(r['total_ms'] or 0)} | {tok} | ${usd:.4f} |"
            )
    else:
        lines.append("_(no generation_cost rows yet — wire-in pending)_")
    lines.append("")

    lines.append("---")
    lines.append(f"_generated at {report['generated_at']}_")
    return "\n".join(lines) + "\n"


def build_report() -> dict:
    init_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    top_engagement = query(
        """
        SELECT article_id,
               MAX(likes) AS likes,
               MAX(comments) AS comments,
               MAX(engagement_score) AS engagement_score,
               MAX(measured_at) AS last_measured
        FROM engagement_log
        WHERE measured_at >= ?
        GROUP BY article_id
        ORDER BY engagement_score DESC
        LIMIT 15
        """,
        (cutoff,),
    )

    grade_distribution = query(
        """
        SELECT overall_grade, COUNT(*) AS n
        FROM regen_history
        WHERE timestamp >= ? AND attempt = 0
        GROUP BY overall_grade
        ORDER BY n DESC
        """,
        (cutoff,),
    )

    # Articles with retry: distinct article_id where any attempt > 0 exists.
    total_articles_row = query(
        "SELECT COUNT(DISTINCT article_id) AS n FROM regen_history "
        "WHERE timestamp >= ?",
        (cutoff,),
    )
    total_articles = total_articles_row[0]["n"] if total_articles_row else 0
    with_retry_row = query(
        "SELECT COUNT(DISTINCT article_id) AS n FROM regen_history "
        "WHERE timestamp >= ? AND attempt > 0",
        (cutoff,),
    )
    articles_with_retry = with_retry_row[0]["n"] if with_retry_row else 0
    retry_pct = (
        articles_with_retry / total_articles * 100
        if total_articles else 0.0
    )

    ab_experiments = query(
        """
        SELECT experiment_id, variant, COUNT(*) AS n,
               AVG(numeric_score) AS avg_score,
               100.0 * SUM(CASE WHEN overall_grade='A' THEN 1 ELSE 0 END)
                     / COUNT(*) AS a_rate
        FROM ab_experiments
        WHERE generated_at >= ?
        GROUP BY experiment_id, variant
        ORDER BY experiment_id, variant
        """,
        (cutoff,),
    )

    cost_summary = query(
        """
        SELECT event_type,
               COUNT(*) AS n,
               SUM(duration_ms) AS total_ms,
               SUM(input_tokens) AS in_tok,
               SUM(output_tokens) AS out_tok,
               SUM(cost_usd) AS cost_usd
        FROM generation_cost
        WHERE timestamp >= ?
        GROUP BY event_type
        ORDER BY n DESC
        """,
        (cutoff,),
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 30,
        "stats": stats(),
        "top_engagement": top_engagement,
        "grade_distribution": grade_distribution,
        "regen_rate": {
            "total_articles": total_articles,
            "articles_with_retry": articles_with_retry,
            "retry_pct": retry_pct,
        },
        "ab_experiments": ab_experiments,
        "cost_summary": cost_summary,
    }


def _push_to_sheets(md: str) -> None:
    """Replace the contents of a 'Telemetry' tab in the existing Sheet
    with the report. Uses the project's SheetsManager. Failures swallowed."""
    try:
        from utils.sheets_manager import SheetsManager
    except ImportError as exc:
        print(f"  WARN: SheetsManager unavailable: {exc}")
        return
    try:
        sm = SheetsManager()
    except Exception as exc:
        print(f"  WARN: Sheets init failed: {exc}")
        return
    if getattr(sm, "_spreadsheet", None) is None and getattr(sm, "_sheet", None) is None:
        print("  WARN: Sheets not configured (creds / sheet id)")
        return
    try:
        spreadsheet = getattr(sm, "_spreadsheet", None) or sm._sheet.spreadsheet
        try:
            ws = spreadsheet.worksheet("Telemetry")
        except Exception:
            ws = spreadsheet.add_worksheet(title="Telemetry", rows=200, cols=8)
        ws.clear()
        # Sheets gets the raw markdown — simple, scannable.
        rows = [[line] for line in md.splitlines()]
        ws.update("A1", rows)
        print("  Sheets: pushed to 'Telemetry' tab")
    except Exception as exc:
        print(f"  WARN: Sheets push failed: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--push-sheets", action="store_true",
        help="Also push the report to a 'Telemetry' tab in the active Sheet",
    )
    parser.add_argument(
        "--out", default=None,
        help="Override the output path (default: docs/knowledge/telemetry_<date>.md)",
    )
    args = parser.parse_args()

    report = build_report()
    md = _format_md(report)
    out_path = (
        Path(args.out)
        if args.out
        else _REPO / "docs" / "knowledge" /
             f"telemetry_{report['generated_at'][:10]}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"DONE: {out_path}")

    if args.push_sheets:
        print("pushing to Sheets ...")
        _push_to_sheets(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
