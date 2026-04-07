"""Article quality scoring via LLM evaluation.

Sends an article to an LLM (via a caller-supplied function) and parses
a structured JSON response containing scores across five dimensions.
The total score is compared against a configurable threshold to
determine whether the article is publication-ready.

Score dimensions (each 0--10):
    - originality
    - accuracy
    - readability
    - citation
    - practicality

Dependencies: json, re (stdlib only)
"""

import json
import logging
import re
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

EVALUATION_PROMPT_TEMPLATE = """\
You are an expert article reviewer.  Evaluate the following article and
return a JSON object with exactly these keys, each scored 0-10:

- originality: novelty of insights and perspective
- accuracy: factual correctness and technical soundness
- readability: clarity, structure, and flow
- citation: proper use of sources and evidence
- practicality: actionable value for the reader

Also include a "feedback" key with a brief explanation (2-3 sentences).

Return ONLY the JSON object, no other text.

---
ARTICLE:
{article}
"""

SCORE_DIMENSIONS: List[str] = [
    "originality",
    "accuracy",
    "readability",
    "citation",
    "practicality",
]

MAX_SCORE_PER_DIM = 10
DEFAULT_MIN_TOTAL = 45

# Regex to extract a JSON object (possibly nested).
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class QualityEvaluator:
    """Evaluate article quality by delegating to an LLM scorer.

    The evaluator is agnostic about which LLM backend is used -- it
    accepts any callable that takes a prompt string and returns a
    response string.
    """

    def __init__(self, prompts_path: Optional[str] = None) -> None:
        """Initialise the evaluator.

        Args:
            prompts_path: Optional path to a YAML file containing a
                ``quality_evaluation_prompt`` key.  When provided, that
                template is used instead of the built-in default.
        """
        self.prompt_template = EVALUATION_PROMPT_TEMPLATE
        if prompts_path:
            self.prompt_template = (
                self._load_evaluation_prompt(prompts_path)
                or EVALUATION_PROMPT_TEMPLATE
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        article: str,
        evaluator_fn: Callable[[str], str],
    ) -> Dict:
        """Send *article* to the LLM for evaluation and return scores.

        Args:
            article: The full article text.
            evaluator_fn: A callable ``(prompt: str) -> str`` that sends
                the prompt to an LLM and returns the raw response.

        Returns:
            A dict with dimension scores (int), ``total`` (int),
            ``feedback`` (str), ``pass`` (bool), and
            ``should_regenerate`` (bool).
        """
        prompt = self.prompt_template.format(article=article)
        logger.info(
            "Requesting quality evaluation (article length: %d).", len(article)
        )

        try:
            response = evaluator_fn(prompt)
            scores = self.parse_evaluation(response)
            logger.info(
                "Evaluation complete: total=%d/50, pass=%s",
                scores.get("total", 0),
                scores.get("pass", False),
            )
            return scores
        except Exception as exc:
            logger.error("Quality evaluation failed: %s", exc)
            return self._default_scores()

    def parse_evaluation(self, response: str) -> Dict:
        """Extract and validate evaluation scores from an LLM response.

        The method tolerates responses wrapped in Markdown code fences
        or containing extra surrounding text.

        Args:
            response: Raw text from the LLM.

        Returns:
            A validated dict with integer scores for each dimension,
            ``total``, ``pass``, ``feedback``, and
            ``should_regenerate``.

        Raises:
            ValueError: If no valid JSON is found or required keys are
                missing.
        """
        json_str = self._extract_json(response)
        if not json_str:
            logger.warning("Could not extract JSON; returning default scores.")
            return self._default_scores()

        try:
            data = json.loads(json_str)
            return self._validate_scores(data)
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse error: %s", exc)
            return self._default_scores()

    @staticmethod
    def meets_threshold(
        scores: Dict,
        min_score: int = DEFAULT_MIN_TOTAL,
    ) -> bool:
        """Return *True* if the total score meets the minimum.

        Args:
            scores: Output of :meth:`evaluate` or :meth:`parse_evaluation`.
            min_score: Minimum acceptable total (default 45 / 50).

        Returns:
            Whether the article passes the quality gate.
        """
        total = scores.get("total", 0)
        result = total >= min_score
        logger.debug(
            "Threshold check: total=%d, min=%d, pass=%s",
            total,
            min_score,
            result,
        )
        return result

    @staticmethod
    def get_feedback(scores: Dict) -> str:
        """Format scores into a human-readable feedback string.

        Args:
            scores: Output of :meth:`evaluate`.

        Returns:
            Multi-line summary suitable for logging or display.
        """
        dim_labels = {
            "originality": "独自性  (Originality) ",
            "accuracy": "正確性  (Accuracy)    ",
            "readability": "可読性  (Readability) ",
            "citation": "引用    (Citation)    ",
            "practicality": "実用性  (Practicality)",
        }

        dim_scores = scores.get("scores", {})
        # Support both flat and nested score layouts.
        lines = ["=== Article Quality Report ==="]
        for dim in SCORE_DIMENSIONS:
            value = dim_scores.get(dim, scores.get(dim, 0))
            bar = "\u2588" * value + "\u2591" * (MAX_SCORE_PER_DIM - value)
            label = dim_labels.get(dim, dim)
            lines.append(f"  {label}: {bar} {value}/{MAX_SCORE_PER_DIM}")

        total = scores.get("total", 0)
        max_total = MAX_SCORE_PER_DIM * len(SCORE_DIMENSIONS)
        lines.append(f"  {'Total':24s}: {total}/{max_total}")
        lines.append("")

        feedback_text = scores.get("feedback", "")
        if feedback_text:
            lines.append(f"Feedback: {feedback_text}")

        if scores.get("should_regenerate"):
            lines.append("-> Regeneration recommended.")

        status = "PASS" if total >= DEFAULT_MIN_TOTAL else "NEEDS REVISION"
        lines.append(f"Status: {status}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_evaluation_prompt(prompts_path: str) -> Optional[str]:
        """Load the evaluation prompt template from a YAML file."""
        try:
            import yaml

            with open(prompts_path, "r", encoding="utf-8") as fh:
                prompts = yaml.safe_load(fh)
            return prompts.get("quality_evaluation_prompt")
        except Exception as exc:
            logger.warning("Failed to load prompts from %s: %s", prompts_path, exc)
            return None

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Find the first JSON object in *text*.

        Checks Markdown code fences first, then bare JSON objects.
        """
        code_block = JSON_BLOCK_RE.search(text)
        if code_block:
            return code_block.group(1)

        match = JSON_OBJECT_RE.search(text)
        if match:
            return match.group(0)

        return None

    @staticmethod
    def _validate_scores(data: Dict) -> Dict:
        """Normalise and clamp score values."""
        raw_scores = data.get("scores", data)
        validated: Dict = {}

        for dim in SCORE_DIMENSIONS:
            value = raw_scores.get(dim, 0)
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 0
            validated[dim] = max(0, min(MAX_SCORE_PER_DIM, value))

        total = sum(validated.values())
        return {
            "scores": validated,
            "total": total,
            "pass": data.get("pass", total >= DEFAULT_MIN_TOTAL),
            "feedback": data.get("feedback", ""),
            "should_regenerate": data.get("should_regenerate", total < 20),
        }

    @staticmethod
    def _default_scores() -> Dict:
        """Return zeroed scores used when evaluation fails."""
        scores = {dim: 0 for dim in SCORE_DIMENSIONS}
        return {
            "scores": scores,
            "total": 0,
            "pass": False,
            "feedback": "Evaluation could not be completed.",
            "should_regenerate": True,
        }
