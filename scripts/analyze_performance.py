"""Cross-join performance × experiment_variant × learn_adoption to find
what actually drives reader engagement on note.com.

Pipeline (runs from ``--learn`` or standalone):

  1. Load ``data/article_performance.jsonl`` (latest row per note key).
  2. Load every ``data/articles/note-*.json`` and build a
     title → scores index (scores carry ``experiment_variant``,
     ``learn_adoption``, ``overall_grade``).
  3. Fuzzy-match performance titles to stored titles so the two sides
     converge even when the publish flow's ``日本語タイトル抽出`` step
     rewrote the title.
  4. Rank the joined rows by ``like_count + 0.5 * comment_count +
     0.1 * anonymous_like_count`` (a simple engagement proxy).
  5. Emit two artifacts:
       - ``docs/knowledge/quality_insights_YYYY-MM-DD.md`` — human-
         readable weekly summary with top/bottom performers and
         flag-level engagement averages.
       - ``docs/knowledge/quality_successes.md`` — prompt-injectable
         block listing the title shapes / adoption patterns of the top
         20 % of articles (counterpart to ``quality_recurring_failures.md``).

Kept intentionally conservative: the feedback loop must not over-fit
on 18 data points. Reports flag confidence by n (sample size).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

if sys.platform == "win32" and __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("analyze_performance")


_PERF_PATH = _REPO / "data" / "article_performance.jsonl"
_ARTICLES_DIR = _REPO / "data" / "articles"
_INSIGHTS_DIR = _REPO / "docs" / "knowledge"
_SUCCESS_PATH = _INSIGHTS_DIR / "quality_successes.md"
_ANTI_PATTERN_PATH = _INSIGHTS_DIR / "quality_anti_patterns.md"


def _engagement_score(row: dict) -> float:
    """Composite engagement proxy. Likes dominate, comments add 0.5,
    anonymous likes add 0.1 (noise-heavy)."""
    return (
        float(row.get("like_count", 0) or 0)
        + 0.5 * float(row.get("comment_count", 0) or 0)
        + 0.1 * float(row.get("anonymous_like_count", 0) or 0)
    )


def _load_latest_performance() -> list[dict]:
    """Keep only the most recently fetched row per article key."""
    if not _PERF_PATH.exists():
        return []
    by_key: dict[str, dict] = {}
    for line in _PERF_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = rec.get("key")
        if not key:
            continue
        prev = by_key.get(key)
        if prev is None or rec.get("fetched_at", "") > prev.get(
            "fetched_at", ""
        ):
            by_key[key] = rec
    return list(by_key.values())


def _load_article_scores() -> list[dict]:
    """Return [{title, article_id, published_url, scores, ...}] for
    every stored note article. ``published_url`` (added 2026-04-23)
    lets the analyzer do an exact join with performance rows instead
    of falling back to fuzzy title match."""
    out: list[dict] = []
    if not _ARTICLES_DIR.exists():
        return out
    for f in _ARTICLES_DIR.glob("note-*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "file": f.name,
            "article_id": d.get("article_id") or f.stem,
            "title": d.get("title") or "",
            "published_url": d.get("published_url") or "",
            "content_length": len(d.get("content") or ""),
            "scores": d.get("scores") or {},
        })
    return out


def _fuzzy_match(perf_title: str, candidates: list[dict]) -> dict | None:
    """Find the stored article whose title most likely corresponds to
    *perf_title*. Matches on both direct title comparison (the stored
    title is the short seed, e.g. ``ノジマ電気``) and the fully-rendered
    publish title (which the extractor replaces with the H1/H2 Jp text).

    Threshold 0.55 — low enough to catch the 『ノジマ電気』→『【地元民
    だけが知る】ノジマ電気の意外な活用術』 rewrite, high enough to avoid
    cross-article noise.
    """
    best: tuple[float, dict | None] = (0.0, None)
    pt = perf_title.lower()
    for c in candidates:
        st = (c.get("title") or "").lower()
        if not st:
            continue
        if st in pt or pt in st:
            return c  # direct substring always wins
        ratio = SequenceMatcher(None, st, pt).ratio()
        if ratio > best[0]:
            best = (ratio, c)
    if best[0] >= 0.55:
        return best[1]
    return None


def _top_pct(rows: list[dict], pct: float) -> list[dict]:
    if not rows:
        return []
    n = max(1, int(len(rows) * pct))
    return sorted(rows, key=_engagement_score, reverse=True)[:n]


def _bottom_pct(rows: list[dict], pct: float) -> list[dict]:
    if not rows:
        return []
    n = max(1, int(len(rows) * pct))
    return sorted(rows, key=_engagement_score)[:n]


def _flag_stats(joined: list[dict]) -> list[tuple[str, dict]]:
    """For each A/B flag seen in the data, compute mean engagement
    with flag=on vs flag=off. Returns ordered by delta so the most
    impactful flag is first.
    """
    buckets: dict[str, list[tuple[bool, float]]] = defaultdict(list)
    for row in joined:
        variant = (row.get("scores") or {}).get("experiment_variant") or {}
        for flag, on in variant.items():
            buckets[flag].append((bool(on), _engagement_score(row)))
    out: list[tuple[str, dict]] = []
    for flag, pairs in buckets.items():
        on_scores = [s for on, s in pairs if on]
        off_scores = [s for on, s in pairs if not on]
        if not on_scores and not off_scores:
            continue
        on_mean = statistics.mean(on_scores) if on_scores else 0.0
        off_mean = statistics.mean(off_scores) if off_scores else 0.0
        out.append((flag, {
            "on_n": len(on_scores),
            "off_n": len(off_scores),
            "on_mean": round(on_mean, 2),
            "off_mean": round(off_mean, 2),
            "delta": round(on_mean - off_mean, 2),
        }))
    out.sort(key=lambda kv: -abs(kv[1]["delta"]))
    return out


def _extract_title_shape(title: str) -> str:
    """Return the dominant pattern (bracket type / prefix tokens) of
    a title so success/failure summaries can group similar articles.
    """
    m = re.match(r"\s*(【[^】]+】)", title)
    if m:
        return m.group(1)
    if title.startswith("「"):
        return "「...」プレフィクス"
    if ":" in title[:20] or "：" in title[:20]:
        return "コロン区切り型"
    return "ブラケット無し"


def main() -> int:
    perf = _load_latest_performance()
    arts = _load_article_scores()
    logger.info(
        "performance rows: %d, article store entries: %d",
        len(perf), len(arts),
    )

    # Build a URL → article index first so we can do an exact join
    # on rows whose ArticleStore entry was updated post-publish. Fall
    # back to fuzzy matching only for the stale tail (older records
    # saved before the published_url write-back was added).
    url_index: dict[str, dict] = {}
    for a in arts:
        pu = (a.get("published_url") or "").strip()
        if pu:
            # Normalize: strip query string so ?app_launch=false etc
            # don't break exact match.
            base = pu.split("?", 1)[0].rstrip("/")
            url_index[base] = a

    joined: list[dict] = []
    unmatched: list[dict] = []
    exact_hits = 0
    for p in perf:
        perf_url = (p.get("url") or "").split("?", 1)[0].rstrip("/")
        m = url_index.get(perf_url) or _fuzzy_match(
            p.get("title", ""), arts,
        )
        row = dict(p)
        if m:
            if url_index.get(perf_url) is m:
                exact_hits += 1
            row["scores"] = m["scores"]
            row["article_id"] = m["article_id"]
            row["content_length"] = m["content_length"]
            row["stored_title"] = m["title"]
            joined.append(row)
        else:
            unmatched.append(p)
    logger.info(
        "joined: %d (%.0f%%) — exact-URL=%d, fuzzy=%d, unmatched=%d",
        len(joined),
        100 * len(joined) / max(1, len(perf)),
        exact_hits,
        len(joined) - exact_hits,
        len(unmatched),
    )
    # Age-bias guard (Codex cross-check 2026-04-23): articles posted
    # under 24h ago haven't had time to accumulate likes; including
    # them in top/bottom would let a freshly-posted hit dominate or
    # a freshly-posted miss tank the bottom. Mature cohort only.
    mature = [r for r in joined if (r.get("age_days") or 0) >= 1.0]
    top = _top_pct(mature, 0.2) if mature else []
    bottom = _bottom_pct(mature, 0.2) if mature else []
    flags = _flag_stats(mature)

    # Codex review (2026-04-23): with n<30 the top-pct ranking is
    # noise-dominated. Gate success-pattern emission behind a minimum
    # sample size so the prompt doesn't start chasing 1-article
    # "successes" on day 1. Insights markdown is still written for
    # the human — only the LLM-facing quality_successes.md is gated.
    _MIN_MATURE_FOR_SUCCESS = 30
    _MIN_TOP_ARTICLES = 5
    success_gate_reason = ""
    if len(mature) < _MIN_MATURE_FOR_SUCCESS:
        success_gate_reason = (
            f"mature(age>=1d)={len(mature)} < {_MIN_MATURE_FOR_SUCCESS}"
            " — sample too small, success_patterns not emitted"
        )
    elif len(top) < _MIN_TOP_ARTICLES:
        success_gate_reason = (
            f"top={len(top)} < {_MIN_TOP_ARTICLES} — "
            "top-pct too small, success_patterns not emitted"
        )

    _INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    insights_path = _INSIGHTS_DIR / f"quality_insights_{today}.md"

    lines = [
        f"# Quality Insights — {today}",
        "",
        f"- 性能データ: {len(perf)}件 / 紐付け成功: {len(joined)}件"
        f" ({len(unmatched)}件unmatched)",
        f"- ScoreCard: `engagement = likes + 0.5*comments + 0.1*anon`",
        "",
        "## トップ記事 (エンゲージメント上位 20%)",
    ]
    for r in top:
        lines.append(
            f"- score={_engagement_score(r):.1f} "
            f"(♥{r.get('like_count', 0)} 💬{r.get('comment_count', 0)}) "
            f"age={r.get('age_days', 0):.1f}d | {r.get('title', '')[:60]}"
        )
    lines.append("")
    lines.append("## 下位記事 (下位 20%)")
    for r in bottom:
        lines.append(
            f"- score={_engagement_score(r):.1f} "
            f"age={r.get('age_days', 0):.1f}d | {r.get('title', '')[:60]}"
        )
    lines.append("")
    lines.append("## A/B フラグ × エンゲージメント")
    lines.append("| flag | on_mean | off_mean | delta | on/off n |")
    lines.append("|---|---|---|---|---|")
    for flag, st in flags[:10]:
        lines.append(
            f"| {flag} | {st['on_mean']} | {st['off_mean']} |"
            f" {'+' if st['delta'] >= 0 else ''}{st['delta']} |"
            f" {st['on_n']}/{st['off_n']} |"
        )
    lines.append("")
    lines.append("## 未マッチ記事 (ArticleStoreに無い/古い)")
    for u in unmatched[:10]:
        lines.append(
            f"- age={u.get('age_days', 0):.1f}d ♥{u.get('like_count', 0)}"
            f" | {u.get('title', '')[:60]}"
        )

    insights_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote insights → %s", insights_path)

    # ---- Prompt-injectable success patterns ----
    if success_gate_reason:
        logger.info("success patterns SKIPPED: %s", success_gate_reason)
        # OVERWRITE any stale pattern file with the waiting stub.
        # Codex review (2026-04-23) flagged that leaving an n=1
        # overfitted success.md in place would push the LLM to chase
        # a random winner. Safer to emit nothing until n>=30.
        _SUCCESS_PATH.write_text(
            "<!-- auto-generated by analyze_performance.py -->\n"
            f"<!-- {datetime.now().isoformat()}: {success_gate_reason} -->\n"
            "# High-engagement 成功パターン (データ蓄積中)\n\n"
            "標本数がまだ少ないため、実績ベースの型抽出は保留中。"
            "学習済みの型 (learn block) を引き続き参照。\n",
            encoding="utf-8",
        )
    elif top:
        shape_counter: dict[str, int] = defaultdict(int)
        for r in top:
            shape = _extract_title_shape(r.get("title", ""))
            shape_counter[shape] += 1
        ranked_shapes = sorted(
            shape_counter.items(), key=lambda kv: -kv[1]
        )

        success_lines = [
            "<!-- auto-generated by scripts/analyze_performance.py -->",
            f"<!-- last updated: {datetime.now().isoformat()} -->",
            "",
            "# High-engagement 成功パターン",
            "",
            f"直近{len(joined)}件中、エンゲージメント上位20%の記事 "
            f"({len(top)}件) から抽出した型。新規生成時の **マネすべき** 型。",
            "",
            "## 採用すべきタイトル型 (エンゲージメント実績ベース)",
        ]
        for shape, count in ranked_shapes[:8]:
            success_lines.append(f"- {shape}: {count}件")
        success_lines.extend([
            "",
            "## 採用すべき具体タイトル例",
        ])
        for r in top[:6]:
            success_lines.append(
                f"- [{r.get('title', '')[:70]}]"
                f"(♥{r.get('like_count', 0)} / "
                f"{r.get('age_days', 0):.1f}日)"
            )
        success_lines.extend([
            "",
            "## 上位記事の採用パターン (learn_adoption 平均)",
        ])
        # Averages of learn_adoption across the top 20%
        if top:
            brackets = sum(
                1 for r in top
                if (r.get("scores") or {})
                    .get("learn_adoption", {})
                    .get("bracket_present")
            )
            tag_cov_values = [
                float((r.get("scores") or {})
                      .get("learn_adoption", {})
                      .get("tag_coverage_pct", 0) or 0)
                for r in top
            ]
            phrase_values = [
                float((r.get("scores") or {})
                      .get("learn_adoption", {})
                      .get("phrase_hits", 0) or 0)
                for r in top
            ]
            success_lines.append(
                f"- bracket採用率: {brackets}/{len(top)}"
                f" ({100*brackets/max(1,len(top)):.0f}%)"
            )
            if tag_cov_values:
                success_lines.append(
                    f"- tag_coverage平均: "
                    f"{statistics.mean(tag_cov_values):.1f}%"
                )
            if phrase_values:
                success_lines.append(
                    f"- phrase_hits平均: "
                    f"{statistics.mean(phrase_values):.2f}"
                )

        success_lines.append("")
        success_lines.append(
            "**この型をベースに新記事を書くと、エンゲージメント期待値が上位20%層に近づく。**"
        )
        _SUCCESS_PATH.write_text(
            "\n".join(success_lines) + "\n", encoding="utf-8",
        )
        logger.info("wrote success patterns → %s", _SUCCESS_PATH)

    # ---- Anti-patterns from bottom 20% (engagement-failure shapes) ----
    # Same gate as success patterns (n >= 30): below that, the bottom
    # is dominated by noise (single-sample misses) and locking it in
    # as "avoid this shape" would over-fit.
    if success_gate_reason:
        # Mirror the waiting-stub strategy used for success patterns —
        # don't leave a stale anti-pattern file around when the sample
        # is too small.
        _ANTI_PATTERN_PATH.write_text(
            "<!-- auto-generated by analyze_performance.py -->\n"
            f"<!-- {datetime.now().isoformat()}: {success_gate_reason} -->\n"
            "# Low-engagement アンチパターン (データ蓄積中)\n\n"
            "標本数がまだ少ないため、実績ベースのアンチパターン抽出は保留中。\n",
            encoding="utf-8",
        )
    elif bottom:
        anti_shape_counter: dict[str, int] = defaultdict(int)
        for r in bottom:
            shape = _extract_title_shape(r.get("title", ""))
            anti_shape_counter[shape] += 1
        anti_ranked = sorted(
            anti_shape_counter.items(), key=lambda kv: -kv[1]
        )

        # Compare top vs bottom shape distribution: a shape that's
        # heavily over-represented in the bottom AND under-represented
        # in the top is the strongest anti-signal.
        top_shapes: dict[str, int] = defaultdict(int)
        for r in top:
            top_shapes[_extract_title_shape(r.get("title", ""))] += 1
        true_anti: list[tuple[str, int, int]] = []
        for shape, bot_n in anti_ranked:
            top_n = top_shapes.get(shape, 0)
            # An anti-pattern: appears in bottom ≥2× AND in top 0×.
            # Captures shapes that consistently flop without ever
            # winning. Looser criteria over-fit on small samples.
            if bot_n >= 2 and top_n == 0:
                true_anti.append((shape, bot_n, top_n))

        anti_lines = [
            "<!-- auto-generated by scripts/analyze_performance.py -->",
            f"<!-- last updated: {datetime.now().isoformat()} -->",
            "",
            "# Low-engagement アンチパターン",
            "",
            f"直近{len(joined)}件中、エンゲージメント下位20%の記事 "
            f"({len(bottom)}件) から抽出した型。新規生成時に **避けるべき** 型。",
            "",
            "## 避けるべきタイトル型 (下位に集中、上位に出ない)",
        ]
        if true_anti:
            for shape, bot_n, _top_n in true_anti[:6]:
                anti_lines.append(
                    f"- {shape}: 下位{bot_n}件 / 上位0件"
                )
        else:
            anti_lines.append("- (該当なし — 下位の型は上位にも分散している)")

        anti_lines.extend([
            "",
            "## 避けるべき具体タイトル例 (engagement最下位)",
        ])
        for r in bottom[:6]:
            anti_lines.append(
                f"- [{r.get('title', '')[:70]}]"
                f"(♥{r.get('like_count', 0)} / "
                f"{r.get('age_days', 0):.1f}日)"
            )

        anti_lines.append("")
        anti_lines.append(
            "**これらの型/トピックは新規生成時に避けるか、"
            "別の切り口で書き直すこと。**"
        )
        _ANTI_PATTERN_PATH.write_text(
            "\n".join(anti_lines) + "\n", encoding="utf-8",
        )
        logger.info("wrote anti-patterns → %s", _ANTI_PATTERN_PATH)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
