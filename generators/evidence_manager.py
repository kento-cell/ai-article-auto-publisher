"""Evidence and citation management for generated articles.

Validates that articles contain proper citations, checks for forbidden
marketing phrases (configurable via settings.yaml), and can
automatically append access dates to URLs.

Dependencies: re (stdlib), datetime (stdlib)
"""

import logging
import re
from datetime import date
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Matches Markdown-style links: [text](url)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")

# Matches bare URLs on their own line or after whitespace.
BARE_URL_RE = re.compile(r"(?<!\()(https?://\S+)")

# Pattern for "accessed YYYY-MM-DD" or similar date annotations.
ACCESS_DATE_RE = re.compile(
    r"(?:accessed|参照|閲覧)[:\s]*\d{4}[-/]\d{1,2}[-/]\d{1,2}",
    re.IGNORECASE,
)


class EvidenceManager:
    """Validate and manage citations and evidence in article text.

    Attributes:
        forbidden_patterns: Compiled regexes for phrases that must not
            appear in published articles.
    """

    def __init__(
        self, forbidden_phrases: Optional[List[str]] = None
    ) -> None:
        """Initialise with optional forbidden-phrase patterns.

        Args:
            forbidden_phrases: Regex strings for disallowed phrases.
                Typically loaded from ``settings.yaml`` under
                ``evidence.forbidden_phrases``.
        """
        self.forbidden_patterns: List[re.Pattern] = []
        for phrase in forbidden_phrases or []:
            try:
                self.forbidden_patterns.append(re.compile(phrase))
            except re.error as exc:
                logger.warning("Invalid regex '%s': %s", phrase, exc)

    # ------------------------------------------------------------------
    # Citation validation
    # ------------------------------------------------------------------

    def validate_citations(self, article: str) -> Dict:
        """Check whether the article contains sufficient citations.

        A citation is defined as a Markdown link whose URL starts with
        ``http(s)://``.  Each citation is also checked for an access-date
        annotation in the surrounding context (within 200 chars after
        the link).

        Args:
            article: Full article text in Markdown.

        Returns:
            A dict with keys:

            - ``is_valid`` (bool): True if at least one citation exists
              and all citations have access dates.
            - ``total_citations`` (int): Number of citations found.
            - ``missing_access_dates`` (list[str]): URLs lacking an
              access-date annotation.
        """
        links = MARKDOWN_LINK_RE.findall(article)
        missing: List[str] = []

        for _text, url in links:
            # Search a window after the URL for an access-date note.
            idx = article.find(url)
            window = article[idx: idx + len(url) + 200]
            if not ACCESS_DATE_RE.search(window):
                missing.append(url)

        is_valid = len(links) > 0 and len(missing) == 0
        result = {
            "is_valid": is_valid,
            "total_citations": len(links),
            "missing_access_dates": missing,
        }
        logger.info("Citation validation: %s", result)
        return result

    # ------------------------------------------------------------------
    # Forbidden-phrase check
    # ------------------------------------------------------------------

    def check_forbidden_phrases(
        self,
        article: str,
        phrases: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Scan the article for forbidden marketing phrases.

        Args:
            article: The article text.
            phrases: Additional regex strings to check beyond those
                provided at init time.

        Returns:
            A list of dicts, each with ``pattern`` (str) and ``match``
            (str) keys, for every violation found.
        """
        patterns = list(self.forbidden_patterns)
        for p in phrases or []:
            try:
                patterns.append(re.compile(p))
            except re.error:
                continue

        violations: List[Dict] = []
        for pat in patterns:
            for match in pat.finditer(article):
                violations.append({
                    "pattern": pat.pattern,
                    "match": match.group(),
                })

        if violations:
            logger.warning("Found %d forbidden-phrase violation(s).", len(violations))
        return violations

    # ------------------------------------------------------------------
    # Access-date helpers
    # ------------------------------------------------------------------

    def add_access_date(
        self, article: str, access_date: Optional[str] = None
    ) -> str:
        """Append today's date to Markdown links missing an access date.

        Only affects links that do not already have an access-date
        annotation nearby.

        Args:
            article: Original Markdown text.
            access_date: Override date string (default: today in
                ``YYYY-MM-DD``).

        Returns:
            Updated article text.
        """
        today = access_date or date.today().isoformat()
        result = article

        for text, url in MARKDOWN_LINK_RE.findall(article):
            idx = result.find(url)
            window = result[idx: idx + len(url) + 200]
            if ACCESS_DATE_RE.search(window):
                continue
            old = f"[{text}]({url})"
            new = f"[{text}]({url}){{.citation}} (accessed {today})"
            result = result.replace(old, new, 1)

        logger.info("Access dates added where missing (date=%s).", today)
        return result

    # ------------------------------------------------------------------
    # Reference section
    # ------------------------------------------------------------------

    @staticmethod
    def generate_reference_section(sources: List[Dict]) -> str:
        """Build a Markdown reference section from a list of sources.

        Each source dict should contain at least ``title`` and ``url``.
        Optional keys: ``author``, ``date``, ``accessed``.

        Args:
            sources: List of source metadata dicts.

        Returns:
            A Markdown string starting with ``## References``.
        """
        if not sources:
            return ""

        lines = ["## References", ""]
        for idx, src in enumerate(sources, start=1):
            title = src.get("title", "Untitled")
            url = src.get("url", "")
            author = src.get("author", "")
            pub_date = src.get("date", "")
            accessed = src.get("accessed", date.today().isoformat())

            parts = []
            if author:
                parts.append(author)
            parts.append(f'"{title}"')
            if pub_date:
                parts.append(f"({pub_date})")
            if url:
                parts.append(f"<{url}>")
            parts.append(f"accessed {accessed}")

            lines.append(f"{idx}. {', '.join(parts)}")

        text = "\n".join(lines) + "\n"
        logger.debug("Generated reference section with %d entries.", len(sources))
        return text
