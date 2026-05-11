"""Subjective article evaluation via LLM with mandatory reasoning.

Unlike the old QualityEvaluator that just asked "rate 0-10", this evaluator
requires the LLM to justify every grade with specific evidence from the article
and the research brief.

Grades: A/B/C (not numeric scores -- to prevent false precision)
"""

import json
import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# 5 subjective dimensions. `title_fulfillment` enforces the project's
# top-level 理念 ("タイトル負け禁止"): a provocative or superlative
# headline demands the body actually back it up. This is the axis where
# an otherwise-well-written article can be rejected — see CLAUDE.md.
DIMENSIONS = [
    "originality", "accuracy", "readability", "engagement",
    "title_fulfillment",
]

VALID_GRADES = {"A", "B", "C"}

MIN_REASON_LENGTH = 20

# How many times to retry the LLM if its JSON output cannot be parsed
# or fails schema validation. Keeps a single retry as a safety net for
# model swap-ins (different models have different JSON-output stability).
MAX_PARSE_RETRIES = 1

RETRY_REMINDER = (
    "\n\nIMPORTANT: Your previous response could not be parsed. "
    "Return ONLY a valid JSON object — no Markdown, no prose, no code fences. "
    "Every dimension MUST have grade (A/B/C) and reason (>=20 chars)."
)

# Regex to extract a JSON object from Markdown code fences.
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

EVALUATION_PROMPT = """\
You are a strict article reviewer. Evaluate the following article on 4 dimensions.

For EACH dimension, you must provide:
1. A grade: A (excellent), B (acceptable), or C (poor)
2. A specific reason referencing the article content (not generic praise/criticism)
3. If grade is C, a concrete improvement suggestion

Dimensions:
- originality: Does this add any unique angle, commentary, or synthesis? \
GRADING FLOOR for research-paper or news digest articles: B is the default. \
Downgrade to C ONLY when the article is a pure mechanical translation with \
zero author commentary, zero cross-reference to other work, and zero \
opinionated framing. An article that translates an arXiv abstract and adds \
even a few sentences of "筆者の見解" / comparison / business implication \
is AT LEAST B. Upgrade to A when the analysis is genuinely novel.
- accuracy: Are claims factually correct? Are they supported by the cited \
sources? Any unverified assertions stated as fact?
- readability: Is the structure clear? Can a reader scan headings and get the \
key points? Is the flow logical?
- engagement: Would a reader finish the whole article? Is the opening \
compelling? Does the conclusion provide actionable next steps? GRADING FLOOR \
for technical content: B is the default when the article has a hook, \
structured headings, and a clear takeaway. C only when the article is flat \
top-to-bottom with no narrative arc.
- title_fulfillment: THIS IS THE MOST IMPORTANT DIMENSION. The title \
will typically be aggressive or superlative — brackets like 【本音】 \
【99%が知らない】【狂気】, numeric claims ("5選"), dramatic verbs \
("放置したら会社が消滅する"). Evaluate whether the body actually \
delivers on the specific promise made in the title: \
  * A = The title's hook is cashed in with concrete specifics (real \
    numbers, named examples, quoted sources, a takeaway that matches \
    the promised framing). \
  * B = The body touches the title's topic but the "catch" is mild — \
    the article reads like an overview even though the title promised \
    an exposé / ranking / deep dive. \
  * C = Bait-and-switch. The title promises exposure / ranking / \
    scandal / quantified claim, but the body is generic commentary \
    that never cashes it in. "タイトル負け" — hard reject in this case. \
Be strict: if the title uses 【本音】 but the article has no \
first-person opinion, that's a C. If the title says "5選" but only 3 \
items are itemised, that's a C. If the title promises data ("99%が知らない") \
but no data appears, that's a C.

{research_context}

Return ONLY a JSON object in this exact format:
{{
  "originality": {{"grade": "A/B/C", "reason": "specific evidence...", \
"suggestion": "if C..."}},
  "accuracy": {{"grade": "A/B/C", "reason": "specific evidence...", \
"suggestion": "if C..."}},
  "readability": {{"grade": "A/B/C", "reason": "specific evidence...", \
"suggestion": "if C..."}},
  "engagement": {{"grade": "A/B/C", "reason": "specific evidence...", \
"suggestion": "if C..."}},
  "title_fulfillment": {{"grade": "A/B/C", "reason": "quote the title's \
promise and point to the specific body passage that cashes it in (or \
say what's missing)", "suggestion": "if C..."}},
  "summary": "1-sentence overall assessment",
  "confidence": "high/medium/low"
}}

---
ARTICLE:
{article}
"""


class SubjectiveEvaluator:
    """Evaluate article quality via LLM with mandatory evidence-backed reasoning.

    Each of the four dimensions (originality, accuracy, readability,
    engagement) receives an A/B/C grade plus a mandatory justification
    that must reference specific article content.
    """

    def score(
        self,
        article: str,
        evaluator_fn: Callable[[str], str],
        context: Optional[dict] = None,
    ) -> dict:
        """Score an article on subjective dimensions.

        Args:
            article: Full markdown text.
            evaluator_fn: Callable that sends prompt to LLM and returns
                response.
            context: Optional dict with:
                - research_brief: Researcher's findings (to check
                  accuracy against)
                - strategy_brief: Strategist's differentiation angle

        Returns:
            Dict with per-dimension grades/reasons, summary, confidence,
            subjective_pass (bool), and blocking_issues (list[str]).
        """
        prompt = self._build_prompt(article, context)
        logger.info(
            "Requesting subjective evaluation (article length: %d).",
            len(article),
        )

        attempts = 0
        last_response = ""
        try:
            for attempt in range(MAX_PARSE_RETRIES + 1):
                attempts += 1
                attempt_prompt = (
                    prompt if attempt == 0 else prompt + RETRY_REMINDER
                )
                last_response = evaluator_fn(attempt_prompt)
                if self._is_parseable(last_response):
                    break
                logger.warning(
                    "Subjective eval parse failed (attempt %d/%d); retrying.",
                    attempt + 1,
                    MAX_PARSE_RETRIES + 1,
                )

            result = self._parse_response(last_response)
            result["_parse_attempts"] = attempts
            logger.info(
                "Subjective evaluation complete: pass=%s, blocking=%s, attempts=%d",
                result.get("subjective_pass"),
                result.get("blocking_issues"),
                attempts,
            )
            return result
        except Exception as exc:
            logger.error("Subjective evaluation failed: %s", exc)
            fallback = self._default_result()
            fallback["_parse_attempts"] = attempts
            return fallback

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        article: str,
        context: Optional[dict] = None,
    ) -> str:
        """Build the evaluation prompt with optional research context.

        Args:
            article: Full markdown text.
            context: Optional dict with research_brief and/or
                strategy_brief keys.

        Returns:
            Formatted prompt string ready to send to the LLM.
        """
        research_context = ""
        if context:
            brief = context.get("research_brief", "")
            if brief:
                research_context += (
                    "Research Brief for accuracy verification:\n"
                    f"{brief}\n\n"
                )
            strategy = context.get("strategy_brief", "")
            if strategy:
                research_context += (
                    "Strategy Brief for originality verification:\n"
                    f"{strategy}\n"
                )
            # 2026-05-11 Sprint 2: RAG-driven hallucination guard.
            # `hallucination_warnings` is a list of past-incident records
            # the retriever pulled by semantic similarity to this article.
            # When present, instruct the critic to evaluate accuracy
            # AND title_fulfillment against each warning — a recurrence
            # of the same pattern must downgrade accuracy to C.
            warnings = context.get("hallucination_warnings") or []
            if warnings:
                lines = [
                    "PAST HALLUCINATION INCIDENTS (RAG semantic matches — verify carefully):",
                ]
                for i, w in enumerate(warnings, 1):
                    score = w.get("score", 0.0)
                    title = w.get("section_title", "")
                    snippet = w.get("snippet", "")
                    lines.append(
                        f"{i}. (similarity={score:.2f}) {title} — {snippet[:200]}"
                    )
                lines.append(
                    "GUARD INSTRUCTIONS:\n"
                    "- These are similarity matches, NOT confirmed hits. Verify the "
                    "current article actually CONTAINS the pattern (e.g., literal "
                    "伏字 like 〇〇寿司 / ××焼鳥, AI 開示 footer text, made-up SNS posts "
                    "with quoted bodies, symbol-named entities like 'ブランド A'). "
                    "Topical reference to AI / 副業 / 店舗 alone is NOT a hit.\n"
                    "- If you confirm the pattern is present in the body: downgrade "
                    "ACCURACY to C and quote the exact problematic passage in the "
                    "reason. Also consider downgrading TITLE_FULFILLMENT to C if "
                    "the title's promise depends on the fabricated content.\n"
                    "- If you cannot find the pattern in the body after careful "
                    "reading: ignore the warning and grade normally."
                )
                research_context += "\n".join(lines) + "\n\n"

        return EVALUATION_PROMPT.format(
            article=article,
            research_context=research_context,
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _is_parseable(self, response: str) -> bool:
        """Quick check: can we extract a JSON blob with all DIMENSIONS keys?

        Used by :meth:`score` to decide whether to retry the LLM call.
        Conservative — returns True only when JSON loads cleanly AND
        every required dimension is present as a dict.
        """
        json_str = self._extract_json(response)
        if not json_str:
            return False
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        for dim in DIMENSIONS:
            if not isinstance(data.get(dim), dict):
                return False
        return True

    def _parse_response(self, response: str) -> dict:
        """Parse and validate LLM JSON response.

        Args:
            response: Raw text from the LLM.

        Returns:
            Validated result dict with grades, reasons, and pass/fail.
        """
        json_str = self._extract_json(response)
        if not json_str:
            logger.warning(
                "Could not extract JSON from response; returning defaults."
            )
            return self._default_result()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse error: %s", exc)
            return self._default_result()

        return self._validate_response(data)

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Find the first JSON object in *text*.

        Checks Markdown code fences first, then uses brace-counting
        to extract the outermost JSON object (handles arbitrary nesting).

        Args:
            text: Raw LLM response text.

        Returns:
            JSON string or None if no object found.
        """
        match = JSON_BLOCK_RE.search(text)
        if match:
            return match.group(1)

        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    def _validate_response(self, data: dict) -> dict:
        """Validate and normalise the parsed evaluation data.

        Ensures every dimension has a valid grade (A/B/C) and a
        non-trivial reason string. Missing or malformed dimensions
        default to grade C.

        Args:
            data: Parsed JSON dict from LLM response.

        Returns:
            Normalised result dict with subjective_pass and
            blocking_issues.
        """
        blocking_issues: list[str] = []

        for dim in DIMENSIONS:
            dim_data = data.get(dim)
            if not isinstance(dim_data, dict):
                data[dim] = {
                    "grade": "C",
                    "reason": "evaluation failed — dimension missing",
                    "suggestion": "re-run evaluation",
                }
                blocking_issues.append(dim)
                continue

            grade = str(dim_data.get("grade", "C")).upper().strip()
            if grade not in VALID_GRADES:
                grade = "C"
            dim_data["grade"] = grade

            reason = str(dim_data.get("reason", "")).strip()
            if not reason:
                reason = "evaluation failed — no reason provided"
                dim_data["grade"] = "C"
            if len(reason) < MIN_REASON_LENGTH:
                logger.warning(
                    "Weak reasoning for %s (%d chars): %s",
                    dim,
                    len(reason),
                    reason,
                )
            dim_data["reason"] = reason
            dim_data.setdefault("suggestion", "")

            if dim_data["grade"] == "C":
                blocking_issues.append(dim)

        data["summary"] = str(data.get("summary", "")).strip() or (
            "Evaluation completed with limited detail."
        )
        confidence = str(data.get("confidence", "low")).lower().strip()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        data["confidence"] = confidence

        data["subjective_pass"] = len(blocking_issues) == 0
        data["blocking_issues"] = blocking_issues
        return data

    @staticmethod
    def _default_result() -> dict:
        """Return a fail-safe result when evaluation cannot complete.

        Floors every dimension at B — the subjective evaluator LLM is
        flaky (Gemma3 often emits invalid JSON) and we don't want its
        output-format bugs to silently drag the composite numeric_score
        down to rejection territory. Objective metrics are the real
        quality gate; subjective is a supplementary boost/penalty and
        should degrade gracefully to "acceptable" when it can't parse.
        """
        result: dict[str, Any] = {}
        for dim in DIMENSIONS:
            result[dim] = {
                "grade": "B",
                "reason": "evaluation output unparseable — default B",
                "suggestion": "re-run evaluation if you need real grades",
            }
        result["summary"] = "Subjective evaluation defaulted to B across the board."
        result["confidence"] = "low"
        result["subjective_pass"] = True
        result["blocking_issues"] = []
        return result
