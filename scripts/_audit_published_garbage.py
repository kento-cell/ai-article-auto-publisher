"""One-shot: audit published note articles for the empty-source-content
fabrication bug (ops_incidents #18).

A Reddit link post arrives with an empty body, so the saved `source`
string contains the literal `'content': ''`. Those articles were
written from a headline alone — fabricated. Lists them newest-first so
the paid ones can be regenerated first.
"""

import glob
import json
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

rows = []
for path in glob.glob(str(_REPO / "data/articles/note-*.json")):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    published_url = data.get("published_url") or ""
    if not published_url:
        continue
    source = data.get("source", "")
    source_str = source if isinstance(source, str) else json.dumps(source)
    # Empty Reddit selftext → literal "'content': ''" in the dict repr.
    empty_content = "'content': ''" in source_str
    is_reddit = "reddit" in source_str.lower()
    saved = (data.get("saved_at") or "")[:10]
    note_id = re.sub(r"\?.*$", "", published_url).rsplit("/", 1)[-1]
    rows.append({
        "date": saved,
        "fabricated": empty_content and is_reddit,
        "note_id": note_id,
        "slug": os.path.basename(path)[:-5],
        "title": (data.get("title") or "")[:60],
    })

rows.sort(key=lambda r: r["date"], reverse=True)
fab = [r for r in rows if r["fabricated"]]

print(f"published note articles: {len(rows)} | fabricated (reddit, empty body): {len(fab)}")
print("-" * 78)
for r in fab:
    print(f"{r['date']} | {r['note_id']:16} | {r['title']}")
print("-" * 78)
print("slugs (for regeneration):")
for r in fab:
    print(f"  {r['slug']}")
