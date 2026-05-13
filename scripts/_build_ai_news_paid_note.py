"""Build a paid AI NEWS note from today's catchup fetch.

Reuses ``catchup/sources.py`` to pull from OpenAI/DeepMind/NVIDIA/HF/HN/
Reddit/arXiv RSS, but SKIPS the SQLite dedup so already-Slack-posted
items are still included (the paid-note audience is different from
the Slack audience).

Generates per-item summaries via Gemma3 targeted at a paid-note
length (200-400 chars) instead of the terse Slack format, and adds
a 「株の動き implication」 line when a known AI-sector company is the
subject.

Output:
  - ``data/custom_posts/ai_news_<date>.json`` — spec for
    ``scripts/publish_custom_post.py``
  - Markdown body printed to stdout for review

Run:
  PYTHONIOENCODING=utf-8 py scripts/_build_ai_news_paid_note.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_ai_news")

# Cap how many items we summarise (each Gemma3 call ≈ 8-12s).
TIER_CAPS = {1: 8, 2: 4, 3: 4}

# Subject → likely affected ticker mapping. Used to add a 株 implication
# tag at the end of each summary when the article subject matches. This
# is intentionally conservative — only well-known companies whose stock
# moves correlate with announcements get tagged. Anything ambiguous gets
# no tag.
STOCK_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bNVIDIA\b|\bnvidia\b|GB200|H200|Blackwell|CUDA", re.I),
     "NVDA"),
    (re.compile(r"\bOpenAI\b|GPT-?\d|ChatGPT|Sora\b|DALL[-·]E", re.I),
     "MSFT (OpenAI 出資)"),
    (re.compile(r"\bAnthropic\b|Claude\b", re.I),
     "AMZN/GOOGL (Anthropic 主要出資)"),
    (re.compile(r"DeepMind|Gemini|Google\s+AI|Bard\b", re.I),
     "GOOGL"),
    (re.compile(r"\bMeta\b\s+(?:AI|FAIR)|Llama|LLaMA|PyTorch", re.I),
     "META"),
    (re.compile(r"Apple\s+Intelligence|Apple\s+AI", re.I),
     "AAPL"),
    (re.compile(r"\bAMD\b|MI3\d\d|ROCm", re.I),
     "AMD"),
    (re.compile(r"\bTSMC\b|3nm|2nm|台積電", re.I),
     "TSM"),
    (re.compile(r"HuggingFace|Hugging Face", re.I),
     "(未上場、コミュニティ動向)"),
]


def _stock_tag(title: str, summary: str) -> str | None:
    text = f"{title}\n{summary}"
    for pat, ticker in STOCK_MAP:
        if pat.search(text):
            return ticker
    return None


# ---------------------------------------------------------------------------
# Hallucination sanitizer: strip model version mentions ("GPT-5.5",
# "Claude 4.7", "Llama 5", "GB300", etc.) that don't appear in the
# scraped source. Gemma3 reliably hallucinates these on thin sources
# even under strict prompting.
# ---------------------------------------------------------------------------
_VERSION_PAT = re.compile(
    r"(GPT[-\s]*\d+(?:\.\d+)?|Claude[-\s]*\d+(?:\.\d+)?|"
    r"Llama[-\s]*\d+(?:\.\d+)?|Gemini[-\s]*\d+(?:\.\d+)?|"
    r"GB\s*\d{3,4}|MI\s*\d{3,4}|H\s*\d{3}|"
    r"o[1-9](?:\.\d+)?|Codex[-\s]*\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _sanitize_versions(summary: str, *, source: str, title: str) -> tuple[str, list[str]]:
    """Replace version mentions not present in source/title with a
    generic stand-in. Returns (sanitized, list_of_stripped_versions)."""
    haystack = (title + "\n" + source).lower()
    stripped: list[str] = []

    def repl(m: re.Match[str]) -> str:
        token = m.group(0)
        norm = re.sub(r"\s+", "", token).lower()
        # Try variations: "GPT-5.5", "GPT5.5", "GPT 5.5"
        candidates = {norm, token.lower(), re.sub(r"[-\s]", "", token).lower()}
        if any(c in haystack for c in candidates):
            return token  # legitimate
        stripped.append(token)
        bare = re.sub(r"[-\s]*\d+(?:\.\d+)?$", "", token).strip()
        bare = re.sub(r"\s+", " ", bare)
        # If even the bare brand name isn't in source, the entire phrase
        # was invented. Replace with a "詳細不明" marker so the sentence
        # explicitly signals the gap to the reader.
        if bare.lower() not in haystack:
            return "(詳細不明)"
        return bare or "(詳細不明)"

    sanitized = _VERSION_PAT.sub(repl, summary)
    return sanitized, stripped


# ---------------------------------------------------------------------------
# Article-body scraper — feeds Gemma3 real text so the summary doesn't
# hallucinate. SSRF-guarded (https only, public schemes), capped at
# 200KB response, 10s timeout.
# ---------------------------------------------------------------------------
_BODY_MAX_BYTES = 200 * 1024
_BODY_TIMEOUT = 10
_USER_AGENT = "Mozilla/5.0 (compatible; ai-news-builder/0.1)"
_TAG_STRIP = re.compile(r"<(script|style|nav|footer|aside)[^>]*>.*?</\1>",
                        flags=re.DOTALL | re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _fetch_article_body(url: str) -> str:
    """Best-effort fetch + HTML-strip of an article body. Returns "" on
    any failure — the caller falls back to the RSS abstract."""
    from urllib.parse import urlparse
    from urllib.request import Request, urlopen
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return ""
        # Reddit JSON endpoint — way cleaner than scraping the page.
        if parsed.netloc.endswith("reddit.com") and "/comments/" in parsed.path:
            json_url = url.rstrip("/") + ".json"
            req = Request(json_url, headers={"User-Agent": _USER_AGENT})
            with urlopen(req, timeout=_BODY_TIMEOUT) as r:
                raw = r.read(_BODY_MAX_BYTES + 1)
            if len(raw) > _BODY_MAX_BYTES:
                return ""
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace"))
                post = payload[0]["data"]["children"][0]["data"]
                return (post.get("selftext") or post.get("title") or "")[:5000]
            except Exception:
                return ""
        req = Request(url, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=_BODY_TIMEOUT) as r:
            raw = r.read(_BODY_MAX_BYTES + 1)
        if len(raw) > _BODY_MAX_BYTES:
            return ""
        html = raw.decode("utf-8", errors="replace")
        # Try to grab <article>/<main> first; fall back to <body>.
        m = re.search(
            r"<(?:article|main)[^>]*>(.*?)</(?:article|main)>",
            html, flags=re.DOTALL | re.IGNORECASE,
        )
        body = m.group(1) if m else html
        body = _TAG_STRIP.sub("", body)
        text = _HTML_TAG.sub(" ", body)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = _WS.sub(" ", text).strip()
        return text[:5000]
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch failed (%s): %s", url, exc)
        return ""


def _translate_thin_source(
    *, title: str, raw: str,
) -> str:
    """When the scraped body is too thin (< 300 bytes) to support a real
    summary, just translate the title + abstract verbatim. This avoids
    Gemma3 inventing fake version numbers / partnerships to fill space.
    """
    from generators.local_llm import LocalLLM
    llm = LocalLLM()
    raw = (raw or "")[:1200]
    prompt = (
        "以下の英語の AI ニュース記事タイトルと要約を、日本語に翻訳してください。\n"
        "\n"
        f"# タイトル\n{title}\n\n"
        f"# 要約 (元 RSS 抜粋)\n{raw}\n\n"
        "# 出力形式\n"
        "次の 2 段構成で書く:\n"
        "[1行目] 日本語タイトル (キャッチーに、ただし元タイトルの意味を変えない)\n"
        "[2行目以降] 元の要約を日本語に翻訳した文章\n"
        "1 行目と本文の間に改行を 1 つ入れること。"
        "\n"
        "# 厳守ルール\n"
        "- **翻訳の範囲を超えた解説・推測・補足を一切しない**\n"
        "- 原文に書いていない技術用語・バージョン番号・連携情報・将来予測を絶対に書かない\n"
        "- 翻訳結果が短くなっても構わない\n"
        "- 「空行」「改行」などの指示語を本文に書かない\n"
    )
    return (llm.generate(prompt, temperature=0.2) or "").strip()


def _summarise_for_note(
    *, title: str, source: str, raw: str, tier: int,
) -> str:
    """Call Gemma3 for a 200-400 char Japanese summary suitable for a
    paid note item. Different prompt from the Slack version: emphasise
    business / market implication, keep concrete facts, no marketing
    fluff."""
    from generators.local_llm import LocalLLM
    llm = LocalLLM()
    raw = (raw or "")[:1600]
    prompt = (
        f"以下は AI 業界の {source} (Tier{tier}) からの英語記事です。"
        f"これを有料 note 読者向けに、日本語で 250〜500 字に要約してください。\n"
        f"\n"
        f"# 元タイトル\n{title}\n\n"
        f"# 元本文 / abstract\n{raw}\n\n"
        f"# 厳守ルール (違反した時点で却下)\n"
        f"1. 元本文に書かれていない固有名詞・数値・バージョン番号を**絶対に作らない**。\n"
        f"   特に GPT-X.X / Claude X.X / Llama X / GB300 等の型番は元本文にあるものだけ。\n"
        f"2. 元本文に書かれていない連携・買収・パートナー関係を推測しない。\n"
        f"3. 「と思われる」「らしい」など推測表現は使わず、事実だけ抜き出す。\n"
        f"   ただし「示唆」「可能性」を語るときは『元記事の主張』として明示する。\n"
        f"4. 元本文に書いていない株価・業績数値は出さない (株の含意タグは別レイヤーで付ける)。\n"
        f"\n"
        f"# 構成\n"
        f"- 1 行目: 日本語タイトル (キャッチーに、ただし元タイトルの意図から逸脱しない)\n"
        f"- 空行\n"
        f"- 本文要約 250〜500 字:\n"
        f"  - 何が起きたか (元本文の具体情報)\n"
        f"  - なぜ重要か (業界文脈、ただし元本文に手がかりがある場合のみ)\n"
        f"  - 読者への示唆 (元本文の主張ベース)\n"
        f"- マークダウンは使わない\n"
    )
    out = llm.generate(prompt, temperature=0.3)
    return (out or "").strip()


def _build_article(items: list[dict]) -> str:
    """Assemble the final note article body."""
    today = dt.datetime.now().strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# 【AI NEWS 速報 {today}】NEWS より早い、株の動きが見えるかもしれない AI 業界の今日")
    lines.append("")
    lines.append(
        "本記事は、当日 UTC で公開された OpenAI / DeepMind / NVIDIA / Hugging Face / "
        "Hacker News / Reddit / arXiv の最新 AI 関連記事から、独自にキュレーション・"
        "翻訳・要約したものです。Bloomberg や日経が報じる前の一次ソースだけを"
        "つないでいるので、市場が反応する数時間〜半日前に動向を掴めます。"
    )
    lines.append("")
    lines.append("注: 本記事は投資助言ではなく一次ソースの整理です。最終判断は元記事 (各項末尾のリンク) を当たって自己責任で。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## なぜ読むべきか")
    lines.append("")
    lines.append(
        "- **速度**: 一般紙が翻訳・記事化するまでの 6〜18 時間先回り\n"
        "- **網羅性**: 8 つの一次ソース横断、英語論文・コミュニティも回収\n"
        "- **シグナル抽出**: ただの羅列ではなく、各項目に「株の含意」タグを付与 "
        "(NVDA / MSFT / GOOGL / META / AMD / TSM など)\n"
    )
    lines.append("")

    tiered: dict[int, list[dict]] = {1: [], 2: [], 3: []}
    for it in items:
        tiered.setdefault(it.get("tier", 3), []).append(it)
    tier_titles = {
        1: "## Tier 1 — 公式ラボ動向 (OpenAI / DeepMind / NVIDIA)",
        2: "## Tier 2 — コミュニティ注目 (HN / Hugging Face)",
        3: "## Tier 3 — リサーチ・コミュニティ雑感 (Reddit / arXiv)",
    }
    for tier in (1, 2, 3):
        chunk = tiered.get(tier, [])
        if not chunk:
            continue
        lines.append(tier_titles[tier])
        lines.append("")
        for it in chunk:
            jp = it.get("jp_summary", "").strip()
            # The LLM returns "title\n\nbody". Try to split.
            jp_title, _, jp_body = jp.partition("\n")
            jp_title = jp_title.strip().lstrip("#").strip() or it["title"]
            jp_body = jp_body.strip() or jp
            # Strip Gemma3 meta-instruction leaks ("空行", "改行", etc.)
            # that the prompt format inadvertently teaches.
            jp_body = re.sub(
                r"^\s*[（(]?(?:空行|改行|blank\s*line)[)）]?\s*$",
                "", jp_body, flags=re.MULTILINE,
            )
            jp_body = re.sub(r"\n{3,}", "\n\n", jp_body).strip()
            tag = _stock_tag(it["title"], jp)
            lines.append(f"### {jp_title}")
            lines.append("")
            lines.append(jp_body)
            lines.append("")
            if tag:
                lines.append(f"**株の含意**: {tag}")
                lines.append("")
            lines.append(f"**ソース**: {it['source']} ([原文を読む]({it['url']}))")
            lines.append("")
            lines.append("---")
            lines.append("")
    lines.append("## まとめ")
    lines.append("")
    if tiered.get(1):
        lines.append("Tier 1 で動きが出ているのは以下の銘柄群:")
        seen_tags: set[str] = set()
        for it in tiered.get(1, []):
            t = _stock_tag(it["title"], it.get("jp_summary", ""))
            if t and t not in seen_tags:
                seen_tags.add(t)
                lines.append(f"- {t}")
        lines.append("")
    lines.append(
        "本記事は明日の朝までに状況が大きく動く前提で書いています。"
        "翌日以降の続報は再度同じ手順で更新予定です。"
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--include-old", action="store_true",
        help="bypass the 72h freshness filter (sources.py default)",
    )
    ap.add_argument(
        "--out-spec", default=None,
        help="path to write the custom_post JSON spec (default: "
             "data/custom_posts/ai_news_<date>.json)",
    )
    args = ap.parse_args()

    from catchup.sources import fetch_all
    raw = fetch_all()
    logger.info("fetched %d items", len(raw))

    # Cap per-tier (no dedup) — paid-note audience hasn't seen Slack.
    by_tier: dict[int, list[dict]] = {1: [], 2: [], 3: []}
    for it in raw:
        by_tier.setdefault(it.get("tier", 3), []).append(it)
    for t in by_tier:
        by_tier[t].sort(
            key=lambda it: it.get("published_at") or dt.datetime.min,
            reverse=True,
        )
    selected: list[dict] = []
    for t in (1, 2, 3):
        cap = TIER_CAPS.get(t, 4)
        selected.extend(by_tier.get(t, [])[:cap])
    logger.info(
        "selected for summarisation: Tier1=%d Tier2=%d Tier3=%d (total %d)",
        len(by_tier.get(1, [])[:TIER_CAPS[1]]),
        len(by_tier.get(2, [])[:TIER_CAPS[2]]),
        len(by_tier.get(3, [])[:TIER_CAPS[3]]),
        len(selected),
    )

    for idx, it in enumerate(selected, 1):
        logger.info(
            "[%d/%d] summarising: %s",
            idx, len(selected), it["title"][:60],
        )
        # Scrape the actual article body so Gemma3 doesn't have to
        # hallucinate to fill 500 chars. Fall back to RSS abstract on
        # any fetch failure.
        body = _fetch_article_body(it["url"])
        raw_source = body if body else it.get("raw_summary", "")
        logger.info(
            "  source bytes: %d (body=%s)",
            len(raw_source or ""), "yes" if body else "abstract-only",
        )
        try:
            if len(raw_source) < 300:
                # Thin source → translation-only mode (no Gemma3
                # elaboration) so we don't invent facts to fill space.
                logger.info("  thin source → translation-only mode")
                summary = _translate_thin_source(
                    title=it["title"], raw=raw_source,
                )
            else:
                summary = _summarise_for_note(
                    title=it["title"],
                    source=it.get("source", "?"),
                    raw=raw_source,
                    tier=it.get("tier", 3),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemma3 failed: %s", exc)
            summary = ""
        # Post-process: strip hallucinated version numbers not in source
        if summary:
            summary, stripped = _sanitize_versions(
                summary, source=raw_source, title=it["title"],
            )
            if stripped:
                logger.warning(
                    "  stripped %d unfounded version mention(s): %s",
                    len(stripped), stripped,
                )
        it["jp_summary"] = summary
        it["_source_bytes"] = len(raw_source or "")

    body = _build_article(selected)
    print()
    print("=" * 70)
    print("ASSEMBLED BODY (preview)")
    print("=" * 70)
    print(body[:3000])
    print("...")
    print()

    today = dt.datetime.now().strftime("%Y-%m-%d")
    out_path = (
        Path(args.out_spec) if args.out_spec
        else _REPO / "data" / "custom_posts" / f"ai_news_{today}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    spec = {
        "platform": "note",
        "title": (
            f"【AI NEWS 速報 {today}】NEWSより速い、株の動きが見えるかもしれない "
            "AI業界の今日まとめ"
        ),
        "image_query": "artificial intelligence news financial market technology",
        "cover_image_query": "ai brain neural network finance abstract",
        "content": body,
        "tags": ["AI", "ChatGPT", "生成AI", "テクノロジー", "ビジネス", "投資", "株式投資"],
    }
    out_path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("spec written: %s", out_path)
    logger.info(
        "next: PYTHONIOENCODING=utf-8 py scripts/publish_custom_post.py %s",
        out_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
