"""Register rescued note articles (from data/articles/*.json) directly to
the Sheets dashboard with status=⏳承認待ち, when Phase 2 hang prevented
Phase 3 (Sheets registration) from running.

2026-05-15: 23rd run hung after 4 note articles passed, so Phase 3 never
ran. ArticleStore has the JSON files but Sheets is empty. Use this helper
to backfill, then `_bulk_approve_note_only.py` → `_publish_free_first.py`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Three rescued note articles (4 passes total; 'Everyone is unhappy'
# was overwritten by re-generation so we have 3 unique survivors).
TARGETS = [
    "note-Zero-day_exploit_com-ce4a843a.json",
    "note-The_AI_Layoff_Bill_I-1ed0597d.json",
    "note-_Everyone_is_unhappy-f89b5415.json",
]


def main() -> int:
    from utils.sheets_manager import SheetsManager

    sm = SheetsManager()
    if sm._sheet is None:
        print("Sheets not configured")
        return 2

    # Avoid duplicate registration — read existing article_ids
    rows = sm._sheet.get_all_values()
    existing_ids = {r[0] for r in rows[1:] if r and r[0]}

    added = 0
    for fname in TARGETS:
        p = _REPO / "data" / "articles" / fname
        if not p.exists():
            print(f"SKIP (missing): {fname}")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        article_id = d.get("article_id") or fname.replace(".json", "")
        if article_id in existing_ids:
            print(f"SKIP (already in sheet): {article_id}")
            continue
        title = d.get("title", "")
        sc = d.get("scores", {})
        det = sc.get("objective_detail", {}) or {}
        subj = sc.get("subjective_detail", {}) or {}

        # Extract metric grades. objective_detail layout varies — try
        # the common shapes first, fall back to "-" when missing.
        def _get_grade(metric: str) -> str:
            m = det.get(metric, {})
            if isinstance(m, dict):
                return str(m.get("grade", "-"))
            return "-"

        def _get_subj(metric: str) -> str:
            m = subj.get(metric, {})
            if isinstance(m, dict):
                return str(m.get("grade", "-"))
            return "-"

        row_data = {
            "article_id": article_id,
            "title": title,
            "status": "⏳承認待ち",
            "evidence_level": sc.get("evidence_level", "A"),
            "overall_grade": sc.get("overall_grade", "B"),
            "platform": d.get("platform", "note"),
            "tier12_ratio": str(sc.get("tier12_ratio", "")),
            "citation_count": _get_grade("citation_count"),
            "visual_count": _get_grade("visual_count"),
            "originality": _get_subj("originality"),
            "accuracy": _get_subj("accuracy"),
            "readability": _get_subj("readability"),
            "engagement": _get_subj("engagement"),
            "critic_summary": (sc.get("summary") or "")[:200],
            "numeric_score": str(sc.get("numeric_score", "")),
        }
        row_num = sm.add_article(row_data)
        print(f"OK row {row_num}: {title[:60]} [{row_data['platform']}, {row_data['overall_grade']}/{row_data['evidence_level']}]")
        added += 1

    print(f"---\nDONE — {added} articles registered as ⏳承認待ち")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
