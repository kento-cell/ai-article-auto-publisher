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

# 4 subjective dimensions
DIMENSIONS = ["originality", "accuracy", "readability", "engagement"]

VALID_GRADES = {"A", "B", "C"}

MIN_REASON_LENGTH = 20

# Regex to extract a JSON object from Markdown code fences.
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

EVALUATION_PROMPT = """\
You are a strict article reviewer. Evaluate the following article on 4 dimensions.

For EACH dimension, you must provide:
1. A grade: A (excellent), B (acceptable), or C (poor)
2. A specific reason referencing the article content (not generic praise/criticism)
3. If grade is C, a concrete improvement suggestion

Dimensions:
- originality: Does this add value beyond summarizing/translating the source? \
Is there a unique angle?
- accuracy: Are claims factually correct? Are they supported by the cited \
sources? Any unverified assertions stated as fact?
- readability: Is the structure clear? Can a reader scan headings and get the \
key points? Is the flow logical?
- engagement: Would a reader finish the whole article? Is the opening \
compelling? Does the conclusion provide actionable next steps?

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

        try:
            response = evaluator_fn(prompt)
            result = self._parse_response(response)
            logger.info(
                "Subjective evaluation complete: pass=%s, blocking=%s",
                result.get("subjective_pass"),
                result.get("blocking_issues"),
            )
            return result
        except Exception as exc:
            logger.error("Subjective evaluation failed: %s", exc)
            return self._default_result()

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

        return EVALUATION_PROMPT.format(
            article=article,
            research_context=research_context,
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

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

        Returns:
            Dict with all dimensions graded C and subjective_pass False.
        """
        result: dict[str, Any] = {}
        for dim in DIMENSIONS:
            result[dim] = {
                "grade": "C",
                "reason": "evaluation could not be completed",
                "suggestion": "re-run evaluation",
            }
        result["summary"] = "Evaluation could not be completed."
        result["confidence"] = "low"
        result["subjective_pass"] = False
        result["blocking_issues"] = list(DIMENSIONS)
        return result
