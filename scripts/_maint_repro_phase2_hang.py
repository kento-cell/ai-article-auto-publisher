"""Maintenance: reproduce the Phase 2 hang that has killed runs 19+20.

Hypothesis (Plan agent v2): the forbidden_phrases regex at
config/settings.yaml:184-186 has nested bounded quantifiers without
anchoring (`そのため(?:[^。]{0,80}。[^そ]{0,300}){2,}そのため` etc).
On gemma4:e4b's 7-8k char output where 「そのため/つまり/一方で」 are
sprinkled liberally, Python's NFA backtracking explodes for 30+ min.

This script feeds a synthetic 7,500-char article (12 occurrences of
each connective, deliberately interleaved) through ObjectiveScorer and
times the forbidden_phrases step alone. If it takes more than ~5s,
TOP1 is confirmed.

Run:
    py scripts/_maint_repro_phase2_hang.py

Exit codes:
    0  finished within 60s — TOP1 unconfirmed (look elsewhere)
    1  exceeded 60s — TOP1 confirmed, patch settings.yaml
"""
from __future__ import annotations
import os, sys, time, signal
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("repro")


def _build_article() -> str:
    """7,500 chars, 12x each of 「そのため」「つまり」「一方で」
    distributed across many short sentences — exactly the gemma4 shape.
    """
    sents = []
    base_filler = "ベクトルDBから最初に10個のドキュメントを取得した後、単に距離が近い順に使うのではなく文脈的に関連性が高いのはどれか別のモデルを使って再評価し並び替える。"
    for i in range(12):
        sents.append(f"RAGは{i}番目のレイヤーで{base_filler}")
        sents.append(f"そのため、検索精度は飛躍的に向上することが報告されている。")
        sents.append(f"つまり、Naive-RAGの限界を越える鍵は再ランキングにあるということ。")
        sents.append(f"一方で、グラフ構造を用いたGraphRAGは別の課題を解決する。")
        sents.append(f"これにより{base_filler[:50]}が改善される。")
    text = "\n".join(sents)
    # Pad to ~7,500 chars
    while len(text) < 7500:
        text += base_filler
    return text[:7500]


def main() -> int:
    import yaml
    settings = yaml.safe_load(
        (_REPO / "config" / "settings.yaml.example").read_text(encoding="utf-8")
    )
    forbidden = settings.get("evidence", {}).get("forbidden_phrases", [])
    # Filter to just the 3 candidate patterns
    candidates = [p for p in forbidden
                  if any(k in p for k in ("そのため", "つまり", "一方で"))]
    log.info("Found %d candidate patterns:", len(candidates))
    for p in candidates:
        log.info("  %r", p)

    article = _build_article()
    log.info("Synthetic article: %d chars", len(article))

    import re
    for p in candidates:
        log.info("--- testing pattern: %s ---", p)
        t0 = time.perf_counter()
        try:
            # Use 30s wall-clock cap via threading (Windows-safe).
            import threading
            result = {"done": False, "matches": None, "exc": None}

            def run():
                try:
                    result["matches"] = re.findall(p, article, re.IGNORECASE)
                    result["done"] = True
                except Exception as e:
                    result["exc"] = e

            t = threading.Thread(target=run, daemon=True)
            t.start()
            t.join(timeout=30.0)
            dt = time.perf_counter() - t0
            if not result["done"]:
                log.error("[HANG CONFIRMED] %.1fs elapsed, regex still running — TOP1 confirmed", dt)
                return 1
            log.info("[ok] %.3fs, %d match(es)", dt, len(result["matches"] or []))
        except Exception as e:
            log.error("error: %s", e)

    log.info("All patterns completed within 30s — TOP1 NOT confirmed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
