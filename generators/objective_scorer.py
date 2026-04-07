"""Objective article scoring via programmatic measurement.

Scores articles on verifiable metrics that don't require LLM judgment.
All measurements are deterministic — the same article always gets the same scores.

Grades: A (excellent), B (acceptable), C (failing — triggers rejection)
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ObjectiveScorer:
    """Score articles using only programmatic, verifiable metrics.

    Every metric is computed by counting or pattern-matching.
    No LLM calls. No subjectivity. Can't lie.
    """

    def score(self, article: str, context: dict | None = None) -> dict:
        """Score an article on all objective dimensions.

        Args:
            article: Full markdown text of the article.
            context: Optional dict with:
                - research_brief: Researcher's output (for tier calculation)
                - sources: list of {url, tier, access_date} dicts
                - forbidden_phrases: list of regex patterns

        Returns:
            Dict with per-metric results, objective_pass bool,
            and blocking_issues list.
        """
        context = context or {}
        forbidden = context.get("forbidden_phrases", [])
        sources = context.get("sources", [])
        chain_blacklist = context.get("chain_blacklist", [])

        evidence = self._score_evidence_level(sources)
        citations = self._score_citation_count(article)
        cite_format = self._score_citation_format(article)
        visuals = self._score_visual_count(article)
        words = self._score_word_count(article)
        forbidden_result = self._score_forbidden_phrases(article, forbidden)
        headings = self._score_heading_structure(article)
        chain_check = self._score_chain_stores(article, chain_blacklist)

        # Collect blocking issues
        blocking: list[str] = []
        metrics_to_check = [
            ("citation_count", citations),
            ("citation_format", cite_format),
            ("visual_count", visuals),
            ("word_count", words),
        ]
        # Only check evidence_level when source data is actually available
        if sources:
            metrics_to_check.insert(0, ("evidence_level", evidence))

        for metric_name, result in metrics_to_check:
            if result["grade"] == "C":
                blocking.append(
                    f"{metric_name}: {result.get('reason', 'grade C')}"
                )

        if forbidden_result["grade"] == "Fail":
            blocking.append(f"forbidden_phrases: {forbidden_result['hits']}")
        if headings["grade"] == "Fail":
            blocking.append(f"heading_structure: {headings['issues']}")
        if chain_check["grade"] == "Fail":
            blocking.append(
                f"chain_stores: チェーン店検出 {chain_check['hits']}"
            )

        objective_pass = len(blocking) == 0

        logger.info(
            "Objective scoring complete: pass=%s, blocking=%d",
            objective_pass,
            len(blocking),
        )

        return {
            "evidence_level": evidence,
            "citation_count": citations,
            "citation_format": cite_format,
            "visual_count": visuals,
            "word_count": words,
            "forbidden_phrases": forbidden_result,
            "heading_structure": headings,
            "chain_stores": chain_check,
            "objective_pass": objective_pass,
            "blocking_issues": blocking,
        }

    # ------------------------------------------------------------------
    # Private scoring methods
    # ------------------------------------------------------------------

    def _score_evidence_level(self, sources: list[dict]) -> dict:
        """Score source quality by tier distribution.

        Args:
            sources: List of dicts, each with a "tier" key (int 1-4).

        Returns:
            Dict with grade, tier12_ratio, total_sources, tier12_count,
            and reason.
        """
        if not sources:
            return {
                "grade": "N/A",
                "tier12_ratio": 0.0,
                "total_sources": 0,
                "tier12_count": 0,
                "reason": "no source data available (skipped)",
            }

        total = len(sources)
        tier12_count = sum(
            1 for s in sources if s.get("tier") in (1, 2)
        )
        ratio = tier12_count / total

        if ratio >= 0.80:
            grade = "A"
            reason = (
                f"{tier12_count}/{total} sources are tier 1-2 "
                f"({ratio:.0%} >= 80%)"
            )
        elif ratio >= 0.60:
            grade = "B"
            reason = (
                f"{tier12_count}/{total} sources are tier 1-2 "
                f"({ratio:.0%}, between 60%-80%)"
            )
        else:
            grade = "C"
            reason = (
                f"{tier12_count}/{total} sources are tier 1-2 "
                f"({ratio:.0%} < 60%)"
            )

        logger.debug("Evidence level: %s (ratio=%.2f)", grade, ratio)
        return {
            "grade": grade,
            "tier12_ratio": round(ratio, 4),
            "total_sources": total,
            "tier12_count": tier12_count,
            "reason": reason,
        }

    def _score_citation_count(self, article: str) -> dict:
        """Count citations in the article text.

        Counts blockquote citation lines (> 出典: / > Source:) and
        markdown links in reference sections.

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade, count, and reason.
        """
        # Blockquote citations: > 出典: or > Source: or > with URL
        blockquote_pattern = re.compile(
            r"^>\s*(?:出典[:：]|Source:|https?://)", re.MULTILINE
        )
        blockquote_hits = blockquote_pattern.findall(article)

        # Reference-section links: lines with [text](url) under a
        # reference heading
        ref_heading = re.compile(
            r"^#{1,3}\s*(?:参考文献|参考|References?|Sources?|出典)",
            re.MULTILINE | re.IGNORECASE,
        )
        ref_links = 0
        match = ref_heading.search(article)
        if match:
            section_text = article[match.end():]
            # Stop at next heading of same or higher level
            next_heading = re.search(r"^#{1,2}\s", section_text, re.MULTILINE)
            if next_heading:
                section_text = section_text[:next_heading.start()]
            ref_links = len(re.findall(
                r"\[.+?\]\(https?://.+?\)", section_text
            ))

        count = len(blockquote_hits) + ref_links

        if count >= 5:
            grade = "A"
            reason = f"{count} citations found (>= 5)"
        elif count >= 2:
            grade = "B"
            reason = f"{count} citations found (2-4 range)"
        else:
            grade = "C"
            reason = f"only {count} citations found (< 2)"

        logger.debug("Citation count: %s (%d)", grade, count)
        return {"grade": grade, "count": count, "reason": reason}

    def _score_citation_format(self, article: str) -> dict:
        """Check citation formatting compliance.

        Each citation should include a URL and an access date.

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade, compliance_rate, with_url, with_date,
            total, and reason.
        """
        # Find all blockquote citation blocks (consecutive > lines)
        citation_blocks = re.findall(
            r"((?:^>.*\n?)+)", article, re.MULTILINE
        )

        if not citation_blocks:
            return {
                "grade": "C",
                "compliance_rate": 0.0,
                "with_url": 0,
                "with_date": 0,
                "total": 0,
                "reason": "no citation blocks found",
            }

        with_url = 0
        with_date = 0
        compliant = 0

        for block in citation_blocks:
            has_url = bool(re.search(r"https?://\S+", block))
            has_date = bool(re.search(
                r"(?:取得日[:：]|accessed[:：]?\s*)", block, re.IGNORECASE
            ))
            if has_url:
                with_url += 1
            if has_date:
                with_date += 1
            if has_url and has_date:
                compliant += 1

        total = len(citation_blocks)
        # Count URL-only compliance (date is nice-to-have for local LLM)
        url_rate = with_url / total if total > 0 else 0.0
        rate = compliant / total if total > 0 else 0.0

        if rate >= 1.0:
            grade = "A"
            reason = f"all {total} citations have URL and access date"
        elif url_rate >= 0.50:
            grade = "B"
            reason = (
                f"{with_url}/{total} citations have URL "
                f"({url_rate:.0%} >= 50%)"
            )
        else:
            grade = "C"
            reason = (
                f"{with_url}/{total} citations have URL "
                f"({url_rate:.0%} < 50%)"
            )

        logger.debug("Citation format: %s (rate=%.2f)", grade, rate)
        return {
            "grade": grade,
            "compliance_rate": round(rate, 4),
            "with_url": with_url,
            "with_date": with_date,
            "total": total,
            "reason": reason,
        }

    def _score_visual_count(self, article: str) -> dict:
        """Count visual elements in the article.

        Counts images, mermaid diagrams, tables, and code blocks.

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade, count, images, mermaid, tables,
            code_blocks, and reason.
        """
        images = len(re.findall(r"!\[", article))
        mermaid = len(re.findall(r"```mermaid", article, re.IGNORECASE))

        # Tables: lines with |...|...| pattern (count unique tables,
        # not rows). A table starts with a |---| separator line.
        table_separators = re.findall(
            r"^\|[\s\-:]+\|", article, re.MULTILINE
        )
        tables = len(table_separators)

        # Code blocks: ``` with a language tag, excluding mermaid
        code_blocks = len(re.findall(
            r"```(?!mermaid)\w+", article, re.IGNORECASE
        ))

        total = images + mermaid + tables + code_blocks

        if total >= 5:
            grade = "A"
            reason = f"{total} visual elements found (>= 5)"
        elif total >= 2:
            grade = "B"
            reason = f"{total} visual elements found (2-4 range)"
        else:
            grade = "C"
            reason = f"only {total} visual elements found (< 2)"

        logger.debug("Visual count: %s (%d total)", grade, total)
        return {
            "grade": grade,
            "count": total,
            "images": images,
            "mermaid": mermaid,
            "tables": tables,
            "code_blocks": code_blocks,
            "reason": reason,
        }

    def _score_word_count(self, article: str) -> dict:
        """Count effective characters (words for Japanese content).

        Strips markdown formatting and counts characters, since for
        Japanese text characters approximate words.

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade, count, target_min, target_max, and reason.
        """
        # Strip markdown syntax for cleaner character count
        text = article
        # Remove code blocks entirely
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Remove images
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        # Remove links but keep text
        text = re.sub(r"\[(.+?)\]\(.*?\)", r"\1", text)
        # Remove heading markers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove bold/italic markers
        text = re.sub(r"[*_]{1,3}", "", text)
        # Remove blockquote markers
        text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
        # Remove table formatting characters
        text = re.sub(r"[|]", "", text)
        # Remove horizontal rules
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # Collapse whitespace
        text = re.sub(r"\s+", "", text)

        count = len(text)
        target_min = 2500
        target_max = 3500

        if target_min <= count <= target_max:
            grade = "A"
            reason = (
                f"{count} chars within target range "
                f"({target_min}-{target_max})"
            )
        elif 2000 <= count <= 4000:
            grade = "B"
            reason = (
                f"{count} chars slightly outside target "
                f"({target_min}-{target_max}) but within 2000-4000"
            )
        else:
            grade = "C"
            reason = f"{count} chars outside acceptable range (2000-4000)"

        logger.debug("Word count: %s (%d chars)", grade, count)
        return {
            "grade": grade,
            "count": count,
            "target_min": target_min,
            "target_max": target_max,
            "reason": reason,
        }

    def _score_forbidden_phrases(
        self, article: str, patterns: list[str]
    ) -> dict:
        """Check for forbidden phrases using regex patterns.

        Args:
            article: Full markdown text.
            patterns: List of regex pattern strings to search for.

        Returns:
            Dict with grade (Pass/Fail), hits list, and reason.
        """
        if not patterns:
            return {
                "grade": "Pass",
                "hits": [],
                "reason": "no forbidden patterns configured",
            }

        hits: list[str] = []
        for pattern in patterns:
            try:
                matches = re.findall(pattern, article, re.IGNORECASE)
                if matches:
                    hits.extend(matches)
            except re.error as exc:
                logger.warning(
                    "Invalid forbidden-phrase regex '%s': %s", pattern, exc
                )

        if hits:
            grade = "Fail"
            reason = f"found {len(hits)} forbidden phrase(s): {hits}"
        else:
            grade = "Pass"
            reason = (
                f"checked {len(patterns)} patterns, no matches found"
            )

        logger.debug("Forbidden phrases: %s (%d hits)", grade, len(hits))
        return {"grade": grade, "hits": hits, "reason": reason}

    def _score_heading_structure(self, article: str) -> dict:
        """Validate markdown heading structure.

        Checks that the article has at least 3 H2 headings and no
        H1 headings in the body (H1 is reserved for the title).

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade (Pass/Fail), h2_count, h3_count, issues
            list, and reason.
        """
        lines = article.split("\n")

        h1_count = 0
        h2_count = 0
        h3_count = 0
        first_line_is_h1 = False
        issues: list[str] = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            # H1: exactly one # followed by space
            if re.match(r"^#\s+\S", stripped):
                if i == 0:
                    first_line_is_h1 = True
                else:
                    h1_count += 1
            elif re.match(r"^##\s+\S", stripped):
                h2_count += 1
            elif re.match(r"^###\s+\S", stripped):
                h3_count += 1

        if h1_count > 0:
            issues.append(
                f"found {h1_count} H1 heading(s) in body "
                "(H1 should only be the title)"
            )
        if h2_count < 3:
            issues.append(
                f"only {h2_count} H2 headings (minimum 3 required)"
            )

        grade = "Pass" if not issues else "Fail"
        if issues:
            reason = "; ".join(issues)
        else:
            reason = (
                f"valid structure: {h2_count} H2 and {h3_count} H3 "
                "headings, no stray H1"
            )

        logger.debug("Heading structure: %s", grade)
        return {
            "grade": grade,
            "h2_count": h2_count,
            "h3_count": h3_count,
            "issues": issues,
            "reason": reason,
        }

    @staticmethod
    def _score_chain_stores(
        article: str, blacklist: list[str]
    ) -> dict:
        """Check if the article mentions any chain store names.

        Chain stores are banned in gourmet/spot recommendation articles.
        Individual, hidden-gem restaurants only.

        Args:
            article: Full markdown text.
            blacklist: List of chain store names to check.

        Returns:
            Dict with grade (Pass/Fail), hits list, and reason.
        """
        if not blacklist:
            return {
                "grade": "Pass",
                "hits": [],
                "reason": "no chain blacklist configured",
            }

        hits: list[str] = []
        for chain in blacklist:
            if chain in article:
                hits.append(chain)

        if hits:
            reason = (
                f"チェーン店検出: {', '.join(hits)}。"
                "個人店・隠れた名店のみ紹介可。チェーン店は禁止。"
            )
            logger.warning("Chain store detected: %s", hits)
            return {"grade": "Fail", "hits": hits, "reason": reason}

        return {
            "grade": "Pass",
            "hits": [],
            "reason": "チェーン店なし",
        }
