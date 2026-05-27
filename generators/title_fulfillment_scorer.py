"""Programmatic title-fulfillment scoring.

Catches mechanical bait-and-switch where the title makes specific
promises but the body fails to deliver. Complements the LLM-based
``title_fulfillment`` dimension in ``subjective_evaluator``: this
module catches deterministic failures (5選 with 3 items, named tool
not in body, claimed timeframe absent), the LLM catches qualitative
ones (promised expose but body reads like an overview).

Top-level rule from CLAUDE.md: "タイトル負け = 読者への裏切り = 絶対禁止".
This scorer is the deterministic enforcement of that rule.

Promise types detected from the title:

* numeric_listicle  -- "5選", "3ツール", "10個" → body must have N items
* time_claim        -- "3ヶ月", "1年" → body must reference the timeframe
* named_entity      -- proper nouns ("Claude", "Cursor") → must appear in body
* bracket_*         -- 【本音】【検証】【完全ガイド】 → body must show the
                       framing (first-person verbs, length, data, etc.)

Grading:

* A = 100% of detected promises fulfilled
* B = 70%-99% fulfilled, OR title has no specific promises (neutral)
* C = <70% fulfilled (タイトル負け — blocking issue)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Promise extraction patterns
# ---------------------------------------------------------------------

# Numeric listicle: digit + counter word.
# Examples: "5選", "3個", "10ツール", "5つ", "3大", "10位".
_NUMERIC_PROMISE_RE = re.compile(
    r"(\d+)\s*"
    r"(?:選|個|つ|大|位|種類|ツール|アプリ|サービス|本|冊|手|箇条"
    r"|の方法|の理由|のコツ|のステップ|のポイント|のテクニック)"
)

# Shop / venue / product counter — same numeric_listicle promise but
# requires extra named-entity verification because a heading count of
# districts (e.g. "## エリア1: 中目黒") trivially satisfies the basic
# list-item check while the body names zero real shops. 2026-05-27
# regression: kc_002 ("個人店 5-6 軒をエリア別に提示") snuck past with
# 8 district H2s but 0 actual shop names.
_SHOP_COUNTER_RE = re.compile(
    r"(\d+)(?:\s*[-〜~]\s*\d+)?\s*"
    r"(?:軒|店舗|店|件|品|箇所|ヶ所|カ所|施設|商品|アイテム|品目)"
)

# Entity signals that prove the body names real shops/products. URL
# patterns are the strongest (an explicit Instagram / Tabelog / Maps
# link is unmistakable intent); bold inline names are a secondary fallback.
_SHOP_ENTITY_URL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(?:instagram\.com/|tabelog\.com/|goo\.gl/maps/|maps\.app\.goo\.gl/"
    r"|hot-pepper\.jp/|hotpepper\.jp/|retty\.me/|gnavi\.co\.jp/)"
    r"[^\s)]+"
)
_SHOP_ENTITY_BOLD_RE = re.compile(
    r"\*\*([\w・A-Za-zぁ-んァ-ヶー]{3,40})\*\*"
)

# Time claims: digit + time unit.
_TIME_PROMISE_RE = re.compile(
    r"(\d+)\s*(?:ヶ月|か月|カ月|年間|年|日間|日|週間|時間)"
)

# Proper nouns: ASCII tokens that look like product/tool names.
_PROPER_NOUN_RE = re.compile(r"([A-Z][A-Za-z][A-Za-z0-9._-]{1,23})")

# Common ASCII words to exclude from proper-noun extraction.
_COMMON_ASCII_WORDS = {
    "AI", "API", "URL", "PDF", "CSV", "SNS", "OS", "IT", "VR", "AR",
    "OK", "NG", "WEB", "NEW", "VS", "LP", "PR", "GPT", "LLM", "ML",
    "UI", "UX", "DB", "SQL", "CSS", "HTML", "JS", "TS", "TV",
    "USA", "EU", "UK", "JP", "KR", "CN", "DX", "CX",
    "QA", "QC", "RPA", "DevOps", "DevTool",
}

# Common English title words — case-insensitive set used to filter out
# pieces of an English news headline that the JSON sometimes carries in
# the `title` field. These are NOT product/tool promises, so excluding
# them avoids false-positive named_entity flags.
_COMMON_ENGLISH_WORDS = {
    "the", "and", "for", "you", "with", "from", "into", "onto", "over",
    "after", "before", "during", "this", "that", "these", "those",
    "multiple", "several", "many", "some", "all", "any",
    "government", "agencies", "agency", "department", "company",
    "president", "ceo", "officer", "officers", "officials", "official",
    "visiting", "warning", "starting", "begins", "ending", "rolls",
    "says", "said", "told", "asks", "tells", "warns",
    "your", "their", "his", "her", "our", "its",
    "have", "has", "had", "will", "would", "could", "should",
    "against", "among", "between", "without", "through",
    "is", "are", "was", "were", "be", "been", "being",
    "more", "most", "less", "few", "first", "last", "next",
    "rolls", "out", "up", "down", "off", "back",
    "tech", "industry", "industries", "workers", "worker", "employees",
    "data", "centers", "center", "users", "user", "customers",
    "study", "report", "research",
    "trump", "biden",  # generic US political figures often in headlines
}

# Bracket framings → required body markers.
# Each category: list of trigger phrases, body markers required to
# fulfill the promise, optional structural requirements (min_chars etc).
_BRACKET_PROMISES: dict[str, dict[str, Any]] = {
    "experience": {
        "triggers": [
            "本音", "リアル", "体験談", "実体験", "実録",
            "検証", "実験", "ガチ", "本気",
            "やってみた", "使ってみた", "試してみた", "使い倒",
        ],
        "body_markers": [
            r"試した", r"検証した", r"使ってみた", r"使ってみる",
            r"やってみた", r"やってみる", r"実際に",
            r"自分で", r"私[はがも]", r"筆者",
            r"\d+(?:時間|日|週間|ヶ月|か月|年).*?(?:使|試|検証|運用|稼働)",
            r"使い倒し", r"使い続け",
        ],
        "min_marker_hits": 1,
    },
    "complete_guide": {
        "triggers": [
            "完全ガイド", "決定版", "保存版", "完全版", "総まとめ",
            "完全攻略", "全網羅", "決定打", "永久保存",
        ],
        "body_markers": [],  # length-only check
        "min_chars": 2200,
    },
    "data_driven": {
        "triggers": [
            "99%が知らない", "99%の人", "9割が", "8割が",
            "データで見る", "データで読む", "数字で見る",
            "調査", "実態", "統計", "ランキング",
        ],
        "body_markers": [
            r"\d+\s*%", r"\d+\s*人", r"\d{3,}", r"\d+\s*件",
            r"(?:約|およそ)\s*\d+", r"\d+\s*(?:倍|分の)",
        ],
        "min_marker_hits": 2,
    },
    "comparison": {
        "triggers": [
            "比較", "vs", "VS", "ＶＳ", "対決", "違い",
            "どっち", "選び方",
        ],
        "body_markers": [],
        # comparison promises require the body to reference 2+ named
        # entities — we enforce this with a separate proper-noun check.
        "min_named_entities": 2,
    },
    "shock_expose": {
        "triggers": [
            "狂気", "衝撃", "やばい", "ヤバい", "ヤバすぎ",
            "終わった", "崩壊", "暴露", "闇", "炎上", "騒動",
            "悲報", "朗報", "驚愕", "戦慄",
        ],
        "body_markers": [
            r"驚", r"衝撃", r"信じ", r"まさか",
            r"異常", r"事態", r"深刻", r"危機", r"問題",
            r"ぞっと", r"ゾッと", r"恐ろしい", r"恐怖",
            r"マジ", r"ガチ", r"本当に", r"まじ",
            r"!", r"！",
        ],
        # Relaxed to 1 hit: the LLM-judged title_fulfillment in
        # subjective_evaluator is the qualitative gate ("did the body
        # actually deliver the shock?"). This deterministic check just
        # ensures the body is at least emotionally coloured rather than
        # being a flat news summary.
        "min_marker_hits": 1,
    },
    "secret_unknown": {
        "triggers": [
            "誰も教え", "誰も知らない", "知らない", "意外と知られて",
            "裏側", "舞台裏", "本当の理由", "真の", "実は",
        ],
        "body_markers": [
            r"実は", r"意外と", r"知られていない", r"あまり知られて",
            r"裏側", r"舞台裏", r"本当の", r"真の",
            r"\d+%(?:の人|しか)", r"普通は", r"一般的には",
        ],
        "min_marker_hits": 1,
    },
}


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def score(title: str, body: str) -> dict:
    """Programmatic title-fulfillment scoring.

    Args:
        title: Article title. Pass the most aggressive framing (the
            published title — usually a marketing-oriented Japanese
            string with brackets and superlatives). If the title is
            mostly ASCII English (legacy source-title carry-over) AND
            the body opens with a Japanese H2 heading, the H2 is used
            instead — that's what the reader actually sees.
        body: Article body text (markdown is fine; we strip lightly).

    Returns:
        Dict with:

        * grade -- "A", "B", or "C"
        * promises -- list of detected title promises
        * unfulfilled -- subset of promises the body did not fulfill
        * fulfillment_ratio -- float in [0, 1]
        * reason -- short human-readable summary
    """
    if not title or not body:
        return _neutral_b("no title or body — neutral B")

    title = _resolve_effective_title(title.strip(), body)
    title = _strip_source_suffix(title)
    body_stripped = _strip_markdown(body)

    promises: list[dict] = []
    unfulfilled: list[dict] = []

    _check_numeric_listicle(title, body_stripped, promises, unfulfilled)
    _check_time_claims(title, body_stripped, promises, unfulfilled)
    _check_named_entities(title, body, body_stripped, promises, unfulfilled)
    _check_bracket_promises(title, body_stripped, promises, unfulfilled)

    if not promises:
        return _neutral_b("title has no specific promises — neutral B")

    fulfilled = len(promises) - len(unfulfilled)
    ratio = fulfilled / len(promises)

    if ratio >= 1.0:
        grade = "A"
        reason = f"all {len(promises)} title promise(s) fulfilled"
    elif ratio >= 0.7:
        grade = "B"
        details = [u.get("detail", "") for u in unfulfilled[:2]]
        reason = (
            f"{len(unfulfilled)}/{len(promises)} unfulfilled "
            f"(acceptable B): {details}"
        )
    else:
        grade = "C"
        details = [u.get("detail", "") for u in unfulfilled[:3]]
        reason = (
            f"タイトル負け: {len(unfulfilled)}/{len(promises)} unfulfilled "
            f"-- {details}"
        )

    logger.info(
        "Title fulfillment: %s (%d/%d promises met)",
        grade, fulfilled, len(promises),
    )
    return {
        "grade": grade,
        "promises": promises,
        "unfulfilled": unfulfilled,
        "fulfillment_ratio": round(ratio, 3),
        "reason": reason,
    }


# ---------------------------------------------------------------------
# Promise checks
# ---------------------------------------------------------------------


def _check_numeric_listicle(
    title: str,
    body: str,
    promises: list[dict],
    unfulfilled: list[dict],
) -> None:
    seen_n: set[int] = set()
    for match in _NUMERIC_PROMISE_RE.finditer(title):
        n = int(match.group(1))
        if n <= 1 or n > 30:
            # 1個 is not a list; >30 is noise (年号や金額の誤検出多発)
            continue
        if n in seen_n:
            continue
        seen_n.add(n)
        promises.append({"type": "numeric_listicle", "expected": n})
        actual = _count_list_items(body)
        if actual < n:
            unfulfilled.append({
                "type": "numeric_listicle",
                "expected": n,
                "actual": actual,
                "detail": (
                    f"title promised {n} items, body has {actual}"
                ),
            })
    # Shop / venue counters — additionally require named-entity proof.
    # Range expressions ("5-6 軒") use the minimum (5) as expected, so
    # the lower bound has to be cleared.
    for match in _SHOP_COUNTER_RE.finditer(title):
        n = int(match.group(1))
        if n <= 1 or n > 30:
            continue
        if n in seen_n:
            # Already handled as a generic numeric listicle; the
            # shop-entity check below still adds value, so don't skip.
            pass
        seen_n.add(n)
        promises.append({"type": "numeric_shop_listicle", "expected": n})
        list_items = _count_list_items(body)
        shop_entities = _count_shop_like_entities(body)
        if list_items < n or shop_entities < n:
            unfulfilled.append({
                "type": "numeric_shop_listicle",
                "expected": n,
                "list_items": list_items,
                "shop_entities": shop_entities,
                "detail": (
                    f"title promised {n} shop/venue items, body has "
                    f"{list_items} headings and {shop_entities} shop "
                    f"entities (URL or bold name) — both must be ≥ {n}"
                ),
            })


def _check_time_claims(
    title: str,
    body: str,
    promises: list[dict],
    unfulfilled: list[dict],
) -> None:
    seen: set[str] = set()
    for match in _TIME_PROMISE_RE.finditer(title):
        timeframe = match.group(0).replace(" ", "")
        if timeframe in seen:
            continue
        seen.add(timeframe)
        promises.append({"type": "time_claim", "timeframe": timeframe})
        # accept loose match: digit + same unit anywhere in body
        n = match.group(1)
        unit_match = re.search(rf"{n}\s*[ヶか]?月|{n}\s*年|{n}\s*日|{n}\s*週", timeframe)
        normalized_unit = unit_match.group(0).replace(" ", "") if unit_match else timeframe
        if normalized_unit not in body and timeframe not in body:
            unfulfilled.append({
                "type": "time_claim",
                "timeframe": timeframe,
                "detail": f"title claims '{timeframe}' but body never mentions it",
            })


def _check_named_entities(
    title: str,
    body_raw: str,
    body_stripped: str,
    promises: list[dict],
    unfulfilled: list[dict],
) -> None:
    # Use raw body for named-entity check — we want to allow the entity
    # to appear inside a code block or link too.
    body_lower = body_raw.lower()
    candidates = _extract_proper_nouns(title)
    seen: set[str] = set()
    for noun in candidates:
        key = noun.lower()
        if key in seen:
            continue
        seen.add(key)
        promises.append({"type": "named_entity", "name": noun})
        if key not in body_lower:
            unfulfilled.append({
                "type": "named_entity",
                "name": noun,
                "detail": f"title names '{noun}' but body doesn't mention it",
            })


def _check_bracket_promises(
    title: str,
    body: str,
    promises: list[dict],
    unfulfilled: list[dict],
) -> None:
    body_lower = body.lower()
    for category, config in _BRACKET_PROMISES.items():
        triggered = _find_bracket_trigger(title, config["triggers"])
        if not triggered:
            continue
        promises.append({
            "type": f"bracket_{category}",
            "trigger": triggered,
        })

        if "min_chars" in config and len(body) < config["min_chars"]:
            unfulfilled.append({
                "type": f"bracket_{category}",
                "trigger": triggered,
                "detail": (
                    f"title hinted {category} ({triggered}) but body is "
                    f"only {len(body)} chars (< {config['min_chars']})"
                ),
            })
            continue

        if "min_named_entities" in config:
            entities = _extract_proper_nouns(body)
            if len(entities) < config["min_named_entities"]:
                unfulfilled.append({
                    "type": f"bracket_{category}",
                    "trigger": triggered,
                    "detail": (
                        f"title hinted {category} ({triggered}) but body has "
                        f"only {len(entities)} named entities "
                        f"(< {config['min_named_entities']})"
                    ),
                })
                continue

        markers = config.get("body_markers", [])
        if markers:
            min_hits = config.get("min_marker_hits", 1)
            hits = 0
            for pattern in markers:
                try:
                    if re.search(pattern, body, re.IGNORECASE):
                        hits += 1
                        if hits >= min_hits:
                            break
                except re.error:
                    continue
            if hits < min_hits:
                unfulfilled.append({
                    "type": f"bracket_{category}",
                    "trigger": triggered,
                    "detail": (
                        f"title hinted {category} ({triggered}) but body "
                        f"has {hits} of {min_hits} required markers"
                    ),
                })


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _find_bracket_trigger(title: str, triggers: list[str]) -> str | None:
    title_lower = title.lower()
    for trigger in triggers:
        if trigger.lower() in title_lower:
            return trigger
    return None


def _count_list_items(body: str) -> int:
    numbered = len(re.findall(
        r"^\s{0,4}\d+[.)、）]\s+\S", body, re.MULTILINE,
    ))
    bulleted = len(re.findall(
        r"^\s{0,4}[\*\-・]\s+\S", body, re.MULTILINE,
    ))
    h2 = len(re.findall(r"^##\s+\S", body, re.MULTILINE))
    h3 = len(re.findall(r"^###\s+\S", body, re.MULTILINE))
    bold_label = len(re.findall(
        r"^\s*\*\*[^*\n]{2,40}\*\*[:：]", body, re.MULTILINE,
    ))
    return max(numbered, bulleted, h2, h3, bold_label)


def _count_shop_like_entities(body: str) -> int:
    """Count distinct shop / venue / product entity references in *body*.

    Used by numeric_shop_listicle promises ("5 軒紹介" etc.). Heading
    count alone is not enough — a body that uses "## エリア1: 中目黒"
    sections without naming any shops passes the generic list-item
    check but is a tile-fulfilment failure. We require either an
    explicit Instagram / Tabelog / Maps URL per shop, OR a bold inline
    name per shop. Bold and URL hits dedupe case-insensitively so the
    same shop mentioned twice still counts as one.
    """
    hits: set[str] = set()
    for m in _SHOP_ENTITY_URL_RE.finditer(body):
        # Dedupe URL by its trailing handle/slug so 'instagram.com/abc'
        # and 'instagram.com/abc/' count as one shop.
        token = m.group(0).rstrip("/").lower()
        hits.add(token)
    for m in _SHOP_ENTITY_BOLD_RE.finditer(body):
        name = m.group(1).strip().lower()
        # Filter generic emphasis like **重要** / **ポイント** that
        # aren't shop names. A 3-char minimum is already in the regex;
        # also reject pure-hiragana strings (heuristic: shop names
        # usually have katakana / ascii / kanji).
        if re.fullmatch(r"[ぁ-ん]+", name):
            continue
        hits.add(name)
    return len(hits)


def _extract_proper_nouns(text: str) -> list[str]:
    """Extract product/tool/proper nouns from *text*.

    Filters out common English words so that English news headlines
    carried in the JSON ``title`` field (e.g., "Hacker Uses Claude and
    ChatGPT to Breach Multiple Government Agencies") don't generate
    false-positive named_entity promises for "Multiple", "Government",
    "Agencies", etc.
    """
    candidates = _PROPER_NOUN_RE.findall(text)
    out: list[str] = []
    for c in candidates:
        if c in _COMMON_ASCII_WORDS:
            continue
        if len(c) < 3:
            continue
        if c.lower() in _COMMON_ENGLISH_WORDS:
            continue
        out.append(c)
    return out


_SOURCE_SUFFIX_RE = re.compile(
    r"\s+[\-\|–—]\s+[A-Z][A-Za-z0-9 ._\-]{2,40}$"
)
_FIRST_H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _resolve_effective_title(title: str, body: str) -> str:
    """Pick the title the reader actually sees.

    If *title* is mostly ASCII (>70%) and the body opens with a Japanese
    H2 heading, prefer the H2 — older pipeline runs sometimes stored
    English source titles in the JSON ``title`` field while the body
    used a Japanese marketing-style H2. Returns *title* unchanged in
    all other cases.
    """
    if not title:
        return title
    ascii_ratio = sum(1 for c in title if ord(c) < 128) / len(title)
    if ascii_ratio <= 0.7:
        return title
    h2_match = _FIRST_H2_RE.search(body)
    if h2_match:
        h2_title = h2_match.group(1).strip()
        if h2_title:
            return h2_title
    return title


def _strip_source_suffix(title: str) -> str:
    """Remove trailing source-attribution like ' - Findy Media' or ' | TechCrunch'.

    RSS aggregator articles often carry the publication name appended
    to the title with ' - <SiteName>' or ' | <SiteName>'. Those words
    are part of the source citation, not a promise to the reader, so
    strip them before extracting named-entity promises.
    """
    return _SOURCE_SUFFIX_RE.sub("", title)


def _strip_markdown(body: str) -> str:
    text = body
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", " ", text)
    text = re.sub(r"\[(.+?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    return text


def _neutral_b(reason: str) -> dict:
    return {
        "grade": "B",
        "promises": [],
        "unfulfilled": [],
        "fulfillment_ratio": 1.0,
        "reason": reason,
    }
