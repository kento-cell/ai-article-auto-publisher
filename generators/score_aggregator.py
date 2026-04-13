"""Score aggregation from objective and subjective evaluations.

Combines ObjectiveScorer and SubjectiveEvaluator results into a final
grade with blocking issues and a human-readable summary.

Key rule: Objective C in ANY metric -> overall C (automatic rejection).
The user never sees C-grade articles.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Subjective dimensions to inspect.
SUBJECTIVE_DIMENSIONS = ["originality", "accuracy", "readability", "engagement"]

# Grade weight for average calculation (A=3, B=2, C=1).
GRADE_VALUE = {"A": 3, "B": 2, "C": 1}

# Numeric-score mapping used for the 0--100 composite. Tuned so that
# "all A" == 100, "all B" == 75, "all C" == 50, matching the grading
# mental model.
GRADE_NUMERIC = {"A": 100.0, "B": 75.0, "C": 50.0}

# Threshold: average >= 2.5 is "B+" territory.
B_PLUS_THRESHOLD = 2.5


class ScoreAggregator:
    """Aggregate objective and subjective scores into a final grade.

    Rules:
    - Objective C anywhere -> overall C (rejection, not shown to user)
    - Objective Fail anywhere -> overall C
    - All objective A + all subjective A -> overall A
    - No objective C + subjective average B+ -> overall B
    - Otherwise -> overall C
    """

    def aggregate(
        self,
        objective: dict,
        subjective: dict,
        context: dict | None = None,
    ) -> dict:
        """Combine scores into final judgment.

        Args:
            objective: Output of ObjectiveScorer.score().
            subjective: Output of SubjectiveEvaluator.score().
            context: Optional metadata dict with slug, title, platform
                keys used to populate the for_sheets section.

        Returns:
            Dict with overall_grade, decision, blocking_issues,
            evidence_level, summary, detail pass-throughs, and
            for_sheets pre-formatted data.
        """
        context = context or {}
        blocking: list[str] = []

        overall_grade, decision = self._compute_grade(
            objective, subjective, blocking,
        )

        evidence_grade = self._extract_evidence_grade(objective)
        ratio = self._extract_tier12_ratio(objective)
        numeric_score = self._compute_numeric_score(objective, subjective)
        summary = self._build_summary(overall_grade, blocking, evidence_grade)

        sheets = self._build_sheets_dict(
            context=context,
            overall_grade=overall_grade,
            decision=decision,
            evidence_grade=evidence_grade,
            ratio=ratio,
            numeric_score=numeric_score,
            objective=objective,
            subjective=subjective,
            summary=summary,
        )

        result = {
            "overall_grade": overall_grade,
            "decision": decision,
            "blocking_issues": blocking,
            "evidence_level": evidence_grade,
            "tier12_ratio": ratio,
            "numeric_score": numeric_score,
            "summary": summary,
            "objective_detail": objective,
            "subjective_detail": subjective,
            "for_sheets": sheets,
        }

        logger.info(
            "Aggregation complete: grade=%s, decision=%s, blocking=%d",
            overall_grade,
            decision,
            len(blocking),
        )
        return result

    # ------------------------------------------------------------------
    # Grade computation
    # ------------------------------------------------------------------

    def _compute_grade(
        self,
        objective: dict,
        subjective: dict,
        blocking: list[str],
    ) -> tuple[str, str]:
        """Determine overall grade and decision from both score sets.

        Mutates *blocking* in place to collect all blocking issues.

        Args:
            objective: Objective scorer output.
            subjective: Subjective evaluator output.
            blocking: Mutable list to accumulate blocking issue names.

        Returns:
            Tuple of (grade, decision).
        """
        obj_pass = objective.get("objective_pass", False)
        obj_blocking = objective.get("blocking_issues", [])
        sub_blocking = subjective.get("blocking_issues", [])

        blocking.extend(
            f"objective:{issue}" for issue in obj_blocking
        )
        blocking.extend(
            f"subjective:{issue}" for issue in sub_blocking
        )

        # Hard rule: objective failure -> reject.
        if not obj_pass:
            logger.info("Objective pass is False -> overall C.")
            return "C", "reject"

        sub_grades = self._collect_subjective_grades(subjective)
        sub_c_count = sub_grades.count("C")
        sub_a_count = sub_grades.count("A")
        obj_all_a = self._all_objective_a(objective)

        # Any subjective C with objective weaknesses -> reject.
        if sub_c_count > 0 and obj_blocking:
            return "C", "reject"

        # Any subjective C (even without objective issues) -> B with notes.
        if sub_c_count > 0:
            return "B", "approve"

        # All A everywhere -> top grade.
        if obj_all_a and sub_a_count == len(SUBJECTIVE_DIMENSIONS):
            return "A", "approve"

        # Check subjective average for B+ threshold.
        avg = self._subjective_average(sub_grades)
        if avg >= B_PLUS_THRESHOLD:
            return "B", "approve"

        # Below threshold -> reject.
        return "C", "reject"

    # ------------------------------------------------------------------
    # Helpers — subjective grade extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_subjective_grades(subjective: dict) -> list[str]:
        """Extract grade letters from subjective evaluation.

        Args:
            subjective: SubjectiveEvaluator output dict.

        Returns:
            List of grade strings (A/B/C) for each dimension.
        """
        grades: list[str] = []
        for dim in SUBJECTIVE_DIMENSIONS:
            dim_data = subjective.get(dim, {})
            grade = str(dim_data.get("grade", "C")).upper().strip()
            if grade not in GRADE_VALUE:
                grade = "C"
            grades.append(grade)
        return grades

    @staticmethod
    def _subjective_average(grades: list[str]) -> float:
        """Compute numeric average of letter grades.

        Args:
            grades: List of grade strings (A/B/C).

        Returns:
            Average as float (A=3, B=2, C=1).
        """
        if not grades:
            return 0.0
        total = sum(GRADE_VALUE.get(g, 1) for g in grades)
        return total / len(grades)

    @classmethod
    def _compute_numeric_score(
        cls,
        objective: dict,
        subjective: dict,
    ) -> float:
        """Return a 0--100 composite score from objective + subjective grades.

        Each metric/dimension contributes its letter-grade numeric value
        (A=100, B=75, C=50). Objective and subjective halves are averaged
        independently so weakness on either side is visible. The two
        halves are then combined 50/50.

        "All A across the board" → 100. "All B" → 75. "All C" → 50.
        Mixed grades land linearly in-between.
        """
        obj_grades: list[str] = []
        for metric_data in (objective.get("metrics") or {}).values():
            if isinstance(metric_data, dict):
                grade = str(metric_data.get("grade", "")).upper().strip()
                if grade in GRADE_NUMERIC:
                    obj_grades.append(grade)

        sub_grades = cls._collect_subjective_grades(subjective)

        if obj_grades:
            obj_score = sum(GRADE_NUMERIC[g] for g in obj_grades) / len(obj_grades)
        else:
            obj_score = GRADE_NUMERIC["C"]

        if sub_grades:
            sub_score = sum(GRADE_NUMERIC[g] for g in sub_grades) / len(sub_grades)
        else:
            sub_score = GRADE_NUMERIC["C"]

        return round(0.5 * obj_score + 0.5 * sub_score, 1)

    @staticmethod
    def _all_objective_a(objective: dict) -> bool:
        """Check whether all objective metrics earned grade A.

        Args:
            objective: ObjectiveScorer output dict.

        Returns:
            True if every metric has grade A.
        """
        metrics = objective.get("metrics", {})
        if not metrics:
            return False
        for metric_data in metrics.values():
            if isinstance(metric_data, dict):
                if metric_data.get("grade", "") != "A":
                    return False
        return True

    # ------------------------------------------------------------------
    # Helpers — objective field extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_evidence_grade(objective: dict) -> str:
        """Extract the evidence-level grade from objective results.

        Args:
            objective: ObjectiveScorer output dict.

        Returns:
            Grade string (A/B/C) or "-" if not available.
        """
        evidence = objective.get("evidence_level", {})
        if isinstance(evidence, dict):
            return str(evidence.get("grade", "-"))
        return "-"

    @staticmethod
    def _extract_tier12_ratio(objective: dict) -> float:
        """Extract tier-1/2 source ratio from objective results.

        Args:
            objective: ObjectiveScorer output dict.

        Returns:
            Ratio as float (0.0 -- 1.0), defaults to 0.0.
        """
        tier = objective.get("tier12_ratio", {})
        if isinstance(tier, dict):
            return float(tier.get("ratio", 0.0))
        if isinstance(tier, (int, float)):
            return float(tier)
        return 0.0

    # ------------------------------------------------------------------
    # Summary / Sheets formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(
        overall_grade: str,
        blocking: list[str],
        evidence_grade: str,
    ) -> str:
        """Generate a one-line summary suitable for a Sheets column.

        Args:
            overall_grade: Final letter grade.
            blocking: List of blocking issue identifiers.
            evidence_grade: Evidence-level grade string.

        Returns:
            Short Japanese summary string.
        """
        if overall_grade == "A":
            return "A: 全指標良好"
        if overall_grade == "C":
            if any("evidence" in b for b in blocking):
                return "C: エビデンス不足"
            if any("visual" in b for b in blocking):
                return "C: 視覚要素不足"
            if blocking:
                return f"C: {blocking[0]} が基準未達"
            return "C: 複合要因で基準未達"
        # Grade B
        if any("visual" in b for b in blocking):
            return "B: 視覚要素不足"
        if evidence_grade == "C":
            return "B: エビデンス改善余地あり"
        if blocking:
            return f"B: {blocking[0]} に改善余地"
        return "B: 概ね良好・軽微な改善余地あり"

    @staticmethod
    def _build_sheets_dict(
        context: dict,
        overall_grade: str,
        decision: str,
        evidence_grade: str,
        ratio: float,
        numeric_score: float,
        objective: dict,
        subjective: dict,
        summary: str,
    ) -> dict:
        """Pre-format data for the Google Sheets critic columns.

        Args:
            context: Metadata dict (slug, title, platform).
            overall_grade: Final letter grade.
            decision: "approve" / "revise" / "reject".
            evidence_grade: Evidence-level grade.
            ratio: Tier-1/2 source ratio.
            objective: Full objective results.
            subjective: Full subjective results.
            summary: One-line summary string.

        Returns:
            Dict keyed to Sheets column names.
        """
        status = (
            "❌自動却下" if decision == "reject" else "⏳承認待ち"
        )
        return {
            "article_id": context.get("slug", ""),
            "title": context.get("title", ""),
            "status": status,
            "evidence_level": evidence_grade,
            "overall_grade": overall_grade,
            "numeric_score": f"{numeric_score:.1f}",
            "platform": context.get("platform", ""),
            "tier12_ratio": f"{ratio:.0%}",
            "citation_count": (
                objective.get("citation_count", {}).get("count", 0)
            ),
            "visual_count": (
                objective.get("visual_count", {}).get("count", 0)
            ),
            "originality": (
                subjective.get("originality", {}).get("grade", "-")
            ),
            "accuracy": (
                subjective.get("accuracy", {}).get("grade", "-")
            ),
            "readability": (
                subjective.get("readability", {}).get("grade", "-")
            ),
            "engagement": (
                subjective.get("engagement", {}).get("grade", "-")
            ),
            "critic_summary": summary,
            "price": 0,
        }
