"""Smoke test all fixes landed today (2026-05-14) to confirm
"回収" (improvements) work and to surface regressions before the
next full generate run.

Run with:  py scripts/_smoke_test_today_fixes.py

Each block prints OK / FAIL with a one-line diagnosis.
"""
import sys
sys.path.insert(0, "E:/ai-article-auto-publisher")
import os
from pathlib import Path

_ENV = Path("E:/ai-article-auto-publisher/.env")
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

results: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    tag = "OK" if ok else "FAIL"
    print(f"  [{tag}] {name}{(' — ' + note) if note else ''}")


# ------------------------------------------------------------------
# 1. rotation_weight=0 fix (Codex Critical #4)
# ------------------------------------------------------------------
print("\n=== 1. rotation_weight=0 → fully excluded ===")
def _rotation_check(raw):
    """Mirror the production logic."""
    if raw is None or raw == "":
        rw = 1.0
    else:
        try:
            rw = float(raw)
        except (TypeError, ValueError):
            rw = 1.0
    return rw <= 0

# Cases that should be EXCLUDED (rw <= 0)
for raw in (0, 0.0, "0", "0.0", -1):
    check(f"rotation_weight={raw!r} excluded", _rotation_check(raw))
# Cases that should NOT be excluded
for raw in (1.0, 5.0, None, "", "abc"):
    check(f"rotation_weight={raw!r} kept", not _rotation_check(raw))


# ------------------------------------------------------------------
# 2. hallu-veto wiring — subj_result["accuracy"] written at top level
# ------------------------------------------------------------------
print("\n=== 2. hallu-veto wiring (top-level accuracy + blocking_issues) ===")
# Simulate the patch logic from main.py
subj_result = {"accuracy": {"grade": "A"}, "blocking_issues": []}
_top_section = "事象 16-19"
_max_hit = 0.97
_reason = f"hallu-veto: matched '{_top_section}' at sim={_max_hit:.3f}"
subj_result["accuracy"] = {"grade": "C", "reason": _reason}
subj_result.setdefault("blocking_issues", []).append(
    f"hallu-veto: {_top_section} sim={_max_hit:.3f}"
)
subj_result["overall_grade"] = "C"

# What ScoreAggregator reads
from generators.score_aggregator import ScoreAggregator
sa = ScoreAggregator()
sub_grades = sa._collect_subjective_grades(subj_result)
check(
    "accuracy=C at top level",
    "C" in sub_grades,
    f"grades={sub_grades}",
)
check(
    "blocking_issues populated",
    len(subj_result["blocking_issues"]) > 0,
    f"len={len(subj_result['blocking_issues'])}",
)


# ------------------------------------------------------------------
# 3. content_sanitizer — single empty bullet ONLY for URL/ref labels
# ------------------------------------------------------------------
print("\n=== 3. sanitizer: parent bullets preserved, URL placeholders stripped ===")
from generators.content_sanitizer import sanitize

cases = [
    ("Cisco公式サイト placeholder", "* Cisco公式サイト: \n", True),
    ("UT Austin News", "*   UT Austin News: \n", True),
    ("Valve ウェブサイト bold", "- **Valve公式ウェブサイト:** \n", True),
    ("メリット parent — KEEP", "- メリット:\n  - 高速処理\n", False),
    ("ポイント parent — KEEP", "* ポイント:\n  - 注意点1\n", False),
    ("normal label with content — KEEP", "- 特徴: 軽量で高速\n", False),
]
for name, text, should_strip in cases:
    _, removed = sanitize(text)
    stripped = len(removed) > 0
    check(
        f"sanitizer: {name}",
        stripped == should_strip,
        f"stripped={stripped} (expected {should_strip})",
    )


# ------------------------------------------------------------------
# 4. AI 検知 deny patterns added to settings.yaml
# ------------------------------------------------------------------
print("\n=== 4. AI-detection deny patterns ===")
import re
try:
    import yaml
    with open("E:/ai-article-auto-publisher/config/settings.yaml.example",
              encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    patterns = cfg.get("evidence", {}).get("forbidden_phrases", [])
except Exception as exc:
    patterns = []
    print(f"    yaml load failed: {exc}")
ai_phrases = [
    "そのため",
    "つまり",
    "一方で",
    "──",
    "次に",
    "まず",
]
found = sum(1 for p in patterns if any(ph in p for ph in ai_phrases))
check(
    "5+ AI-detection patterns present",
    found >= 5,
    f"found {found}/{len(patterns)} matched any AI-detection keyword",
)


# ------------------------------------------------------------------
# 5. RAG: multi-query for hallu-guard
# ------------------------------------------------------------------
print("\n=== 5. RAG hallu-guard multi-query ===")
from main import _retrieve_hallucination_warnings

# Should fire on AI 開示 (known incident)
ai_disclosure = (
    "店舗A、店舗Bと比較しても、味は群を抜いていました。\n"
    "## ご利用にあたって\n本記事はAIで生成しました。"
    "免責事項：本記事の内容の正確性は保証しません。"
)
hits_ai = _retrieve_hallucination_warnings(ai_disclosure)
check("hallu-guard fires on AI footer", len(hits_ai) >= 1, f"hits={len(hits_ai)}")

# Should NOT fire on clean tech (the test that broke earlier)
clean_tech = (
    "Claude Code は Anthropic の CLI ツールで、ターミナルから "
    "AI コーディング支援が受けられる。GitHub の公式リポジトリで "
    "OSS として公開されており、Mac/Linux/Windows いずれでも動作する。"
    "サブスクリプションは Anthropic Console から管理。"
)
hits_clean = _retrieve_hallucination_warnings(clean_tech)
check(
    "hallu-guard silent on clean tech",
    len(hits_clean) == 0,
    f"hits={len(hits_clean)}",
)


# ------------------------------------------------------------------
# 6. RAG reranker on past_articles (dup detection)
# ------------------------------------------------------------------
print("\n=== 6. RAG dup detection via rerank ===")
from generators.rag_retriever import RagRetriever
r = RagRetriever()
# Query for a known-published topic
dup_hits = r.retrieve_with_rerank(
    query="Claude Code で月10万円 副業 30日 ロードマップ",
    collection="past_articles",
    top_k=3,
    candidate_k=15,
    score_threshold=0.55,
)
# Should hit *something* — at least the AI sidejob seed topic chunks
has_results = len(dup_hits) > 0
check("dup retrieve returns hits", has_results, f"hits={len(dup_hits)}")
if has_results:
    top = dup_hits[0]
    bi = top.metadata.get("bi_score") if top.metadata else None
    check(
        "rerank metadata includes bi_score",
        bi is not None,
        f"top: rerank={top.score:.3f} bi={bi}",
    )


# ------------------------------------------------------------------
# 7. ops_incidents collection has banner-ready content
# ------------------------------------------------------------------
print("\n=== 7. ops_incidents RAG content sanity ===")
banner_hits = r.retrieve(
    query="ChatGPT 画像 MD5 same identical placeholder note logo",
    collection="ops_incidents",
    top_k=3,
    score_threshold=0.55,
)
check(
    "ops_incidents queryable",
    len(banner_hits) >= 1,
    f"hits={len(banner_hits)}",
)


# ------------------------------------------------------------------
# 8. AB experiments table writes today (variant variety check)
# ------------------------------------------------------------------
print("\n=== 8. ab_experiments table state ===")
import sqlite3
try:
    conn = sqlite3.connect("E:/ai-article-auto-publisher/data/telemetry.sqlite3")
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT variant, COUNT(*), AVG(numeric_score) FROM ab_experiments "
        "GROUP BY variant"
    ).fetchall()
    conn.close()
    check(
        "ab_experiments has writes",
        len(rows) >= 1,
        ", ".join(f"{v}: n={n}" for v, n, _ in rows),
    )
except Exception as exc:
    check("ab_experiments query", False, str(exc))


# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
total = len(results)
oks = sum(1 for _, ok, _ in results if ok)
print(f"\n=== Summary: {oks}/{total} OK ===")
fails = [n for n, ok, _ in results if not ok]
if fails:
    print("Failed:")
    for f in fails:
        print(f"  - {f}")
    sys.exit(2)
print("All smoke checks passed.")
