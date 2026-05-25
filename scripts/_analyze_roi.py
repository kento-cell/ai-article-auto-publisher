"""ROI analysis: aggregate publish/grade/price/membership/engagement across data/articles/*.json.

Read-only one-shot for analyst report.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART_DIR = ROOT / "data" / "articles"

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
cutoff_30 = now - timedelta(days=30)
cutoff_14 = now - timedelta(days=14)
cutoff_7 = now - timedelta(days=7)


def parse_dt(s):
    if not s:
        return None
    try:
        # tolerate Z and timezone-naive
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST)
    except Exception:
        return None


files = sorted(ART_DIR.glob("*.json"))
print(f"# Total article JSON files: {len(files)}")

rows = []
schema_keys = Counter()
for fp in files:
    try:
        with fp.open("r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        continue
    rows.append((fp.name, d))
    for k in d.keys():
        schema_keys[k] += 1

print(f"\n# Schema keys (top 40):")
for k, c in schema_keys.most_common(40):
    print(f"  {k}: {c}")


def field(d, *names, default=None):
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return default


# Bucket by platform + published date
buckets = defaultdict(list)
all_published = []
for name, d in rows:
    # heuristics: platform from filename prefix or field
    plat = field(d, "platform", "target_platform")
    if not plat:
        if name.startswith("zenn-"):
            plat = "zenn"
        elif name.startswith("note-"):
            plat = "note"
        else:
            plat = "unknown"

    pub_url = field(d, "published_url", "publish_url", "url")
    pub_at_raw = field(d, "published_at", "publish_at", "published_time", "publishedAt")
    pub_at = parse_dt(pub_at_raw) if pub_at_raw else None

    # Detect zenn scrap vs article
    sub_type = "article"
    if plat == "zenn":
        if pub_url and "/scraps/" in pub_url:
            sub_type = "scrap"
        elif d.get("zenn_scrap_only") or d.get("is_scrap"):
            sub_type = "scrap"

    # Price
    price = field(d, "price", "note_price", "publish_price")
    try:
        price = int(price) if price is not None else None
    except (TypeError, ValueError):
        price = None

    # Grade — primary location is scores.overall_grade
    grade = field(d, "grade", "final_grade", "overall_grade")
    scores = d.get("scores") or {}
    if isinstance(scores, dict):
        grade = grade or scores.get("overall_grade")
        obj_grade = scores.get("evidence_level")  # use evidence_level as proxy for objective
        subj_grade = None
        # subjective_detail may have per-axis grades
        sd = scores.get("subjective_detail") or {}
        if isinstance(sd, dict):
            subj_axes = [v.get("grade") for v in sd.values() if isinstance(v, dict) and "grade" in v]
            if subj_axes:
                # mode/most common A/B/C
                from collections import Counter as _C
                subj_grade = _C(subj_axes).most_common(1)[0][0]
        evidence_grade = scores.get("evidence_level")
        numeric_score = scores.get("numeric_score")
    else:
        obj_grade = subj_grade = evidence_grade = numeric_score = None

    # Membership flag
    mem_flag = field(d, "membership_added", "membership_success", "added_to_membership", default=False)

    is_published = bool(pub_url)

    rec = {
        "name": name,
        "platform": plat,
        "sub_type": sub_type,
        "published": is_published,
        "published_url": pub_url,
        "published_at": pub_at,
        "price": price,
        "grade": grade,
        "obj_grade": obj_grade,
        "subj_grade": subj_grade,
        "evidence_grade": evidence_grade,
        "numeric_score": numeric_score,
        "membership_added": bool(mem_flag),
        "title": field(d, "title"),
    }
    rows_proc = rec
    if is_published and pub_at:
        all_published.append(rec)

print(f"\n# Published with timestamp: {len(all_published)}")

# 30-day window
last30 = [r for r in all_published if r["published_at"] >= cutoff_30]
last14 = [r for r in all_published if r["published_at"] >= cutoff_14]
last7 = [r for r in all_published if r["published_at"] >= cutoff_7]

print(f"# Published last 30 days: {len(last30)}")
print(f"# Published last 14 days: {len(last14)}")
print(f"# Published last 7 days: {len(last7)}")


def summarize(name, recs):
    print(f"\n## {name} (n={len(recs)})")
    plat_sub = Counter((r["platform"], r["sub_type"]) for r in recs)
    print("  platform x sub_type:")
    for k, c in plat_sub.most_common():
        print(f"    {k}: {c}")

    # note paid vs free
    note_recs = [r for r in recs if r["platform"] == "note"]
    paid = [r for r in note_recs if (r["price"] or 0) > 0]
    free = [r for r in note_recs if (r["price"] or 0) == 0]
    print(f"  note paid: {len(paid)}, note free: {len(free)}")

    # price distribution (note)
    price_ctr = Counter(r["price"] for r in note_recs)
    print("  note price distribution:")
    for p, c in sorted(price_ctr.items(), key=lambda x: (x[0] is None, x[0] or 0)):
        print(f"    ¥{p}: {c}")

    # grade dist
    grades = Counter(r["grade"] for r in recs)
    print("  overall_grade:")
    for g, c in grades.most_common():
        print(f"    {g}: {c}")
    # evidence_grade
    ev = Counter(r["evidence_grade"] for r in recs)
    print("  evidence_grade:")
    for g, c in ev.most_common():
        print(f"    {g}: {c}")
    # subjective grade mode
    sj = Counter(r["subj_grade"] for r in recs)
    print("  subjective_grade (mode of axes):")
    for g, c in sj.most_common():
        print(f"    {g}: {c}")
    # numeric score: median
    ns = sorted(r["numeric_score"] for r in recs if isinstance(r["numeric_score"], (int, float)))
    if ns:
        med = ns[len(ns)//2]
        mn = min(ns); mx = max(ns)
        avg = sum(ns)/len(ns)
        print(f"  numeric_score: n={len(ns)} median={med} avg={avg:.1f} min={mn} max={mx}")

    # revenue estimate (note paid only, at face price)
    rev = sum((r["price"] or 0) for r in note_recs)
    print(f"  note gross face revenue (sum of price tags): ¥{rev:,}")

    # membership added stats
    mem_added = sum(1 for r in note_recs if r["membership_added"])
    print(f"  note membership_added flag true: {mem_added} / {len(note_recs)}")


summarize("Last 30 days", last30)
summarize("Last 14 days", last14)
summarize("Last 7 days", last7)
summarize("All time", all_published)

# Daily publish cadence last 30
by_day = Counter()
for r in last30:
    day = r["published_at"].date().isoformat()
    by_day[day] += 1
print("\n# Daily publish count (last 30):")
for day in sorted(by_day.keys()):
    print(f"  {day}: {by_day[day]}")

# Top recent note paid (last 14)
print("\n# Recent note paid (last 14, sorted desc):")
note_paid_14 = sorted(
    [r for r in last14 if r["platform"] == "note" and (r["price"] or 0) > 0],
    key=lambda x: x["published_at"], reverse=True,
)
for r in note_paid_14[:40]:
    print(f"  {r['published_at'].strftime('%m-%d %H:%M')} ¥{r['price']} {r['grade']} | {(r['title'] or r['name'])[:80]}")

# Recent note free (last 14)
print("\n# Recent note free (last 14):")
note_free_14 = sorted(
    [r for r in last14 if r["platform"] == "note" and (r["price"] or 0) == 0],
    key=lambda x: x["published_at"], reverse=True,
)
for r in note_free_14[:40]:
    print(f"  {r['published_at'].strftime('%m-%d %H:%M')} ¥0 {r['grade']} | {(r['title'] or r['name'])[:80]}")

# Zenn scrap vs article ratio
print("\n# Zenn breakdown (all time):")
zenn_all = [r for r in all_published if r["platform"] == "zenn"]
zenn_sub = Counter(r["sub_type"] for r in zenn_all)
for k, c in zenn_sub.items():
    print(f"  {k}: {c}")
zenn_30 = [r for r in last30 if r["platform"] == "zenn"]
zenn_sub_30 = Counter(r["sub_type"] for r in zenn_30)
print("# Zenn breakdown (last 30):")
for k, c in zenn_sub_30.items():
    print(f"  {k}: {c}")
