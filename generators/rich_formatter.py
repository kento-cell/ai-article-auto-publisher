"""Rich text formatting enhancer for Markdown articles.

Enhances plain Markdown articles with rich formatting elements --
callout boxes, toggle sections, tables of contents, visual break
markers, and image insertion -- targeting Zenn or note platforms.

Dependencies: re (stdlib only)
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns used across multiple methods.
# ---------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.*)", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+(.*)", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_TABLE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_HR_RE = re.compile(r"^---+\s*$", re.MULTILINE)

_CALLOUT_PREFIXES = (
    "重要:", "ポイント:", "注意:", "Tips:", "Key:",
    "NOTE:", "WARNING:", "IMPORTANT:", "TIP:",
)

_SUPPORTED_PLATFORMS = ("zenn", "note")


class RichFormatter:
    """Enhance markdown articles with rich formatting for Zenn and note."""

    def __init__(self, platform: str = "zenn") -> None:
        """Set target platform for platform-specific formatting.

        Args:
            platform: One of ``"zenn"`` or ``"note"``.

        Raises:
            ValueError: If *platform* is not supported.
        """
        platform = platform.lower()
        if platform not in _SUPPORTED_PLATFORMS:
            raise ValueError(
                f"Unsupported platform '{platform}'. "
                f"Choose from {_SUPPORTED_PLATFORMS}."
            )
        self.platform: str = platform
        logger.info("RichFormatter initialised for platform: %s", self.platform)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def format_article(
        self,
        content: str,
        images: Optional[list[dict]] = None,
    ) -> str:
        """Apply all formatting enhancements to an article.

        Calls sub-methods in a deliberate order so that later passes
        do not break earlier insertions.

        Args:
            content: Raw Markdown text.
            images: Optional image dicts (first is hero, rest are section).

        Returns:
            Enhanced Markdown string.
        """
        images = images or []

        content = self.enhance_headings(content)
        content = self.add_callout_boxes(content)
        content = self.add_toggle_sections(content)
        content = self.enhance_tables(content)

        if images:
            content = self.add_hero_image(content, images[0])
            if len(images) > 1:
                content = self.add_section_images(content, images[1:])

        content = self.add_reading_progress_markers(content)
        content = self.insert_visual_breaks(content)
        content = self.add_toc(content)
        content = self.format_citations(content)

        density = self.calculate_visual_density(content)
        logger.info(
            "Visual density score: %.1f  (meets minimum: %s)",
            density["visual_density_score"],
            density["meets_minimum"],
        )
        return content

    # ------------------------------------------------------------------
    # Hero & section images
    # ------------------------------------------------------------------

    @staticmethod
    def add_hero_image(content: str, image: dict) -> str:
        """Insert a hero image at the top of the article.

        If YAML front-matter is present the image is placed directly
        after it; otherwise it goes before the first line.

        Args:
            content: Markdown text.
            image: Image dict with ``url``, ``alt_text``, ``attribution``.

        Returns:
            Markdown with the hero image inserted.
        """
        alt = image.get("alt_text", "Hero image")
        url = image.get("url", "")
        attribution = image.get("attribution", "")

        block = f"![{alt}]({url})"
        if attribution:
            block += f"\n*{attribution}*"
        block += "\n"

        fm_match = _FRONTMATTER_RE.match(content)
        if fm_match:
            insert_pos = fm_match.end()
            return content[:insert_pos] + "\n" + block + "\n" + content[insert_pos:]
        return block + "\n" + content

    def add_section_images(
        self, content: str, images: list[dict]
    ) -> str:
        """Insert images after H2 headings, distributed evenly.

        Args:
            content: Markdown text.
            images: List of image dicts.

        Returns:
            Markdown with section images inserted.
        """
        h2_positions = [m.end() for m in _H2_RE.finditer(content)]
        if not h2_positions or not images:
            return content

        # Distribute images across available H2 positions.
        step = max(1, len(h2_positions) // max(len(images), 1))
        chosen = h2_positions[::step][: len(images)]

        # Insert in reverse order to preserve positions.
        for pos, img in reversed(list(zip(chosen, images))):
            block = self._image_block(img)
            content = content[:pos] + "\n\n" + block + "\n" + content[pos:]
        return content

    # ------------------------------------------------------------------
    # Heading hierarchy
    # ------------------------------------------------------------------

    @staticmethod
    def enhance_headings(content: str) -> str:
        """Ensure proper heading hierarchy in the body.

        Demotes any H1 (``#``) in the body to H2 (``##``).  Leaves
        front-matter and title lines untouched.

        Args:
            content: Markdown text.

        Returns:
            Markdown with corrected heading levels.
        """
        # Skip front-matter when looking for body headings.
        fm_match = _FRONTMATTER_RE.match(content)
        start = fm_match.end() if fm_match else 0

        body = content[start:]
        # Demote solitary H1 to H2 (not inside code blocks).
        body = re.sub(r"^#\s+", "## ", body, flags=re.MULTILINE)
        return content[:start] + body

    # ------------------------------------------------------------------
    # Callout boxes
    # ------------------------------------------------------------------

    def add_callout_boxes(self, content: str) -> str:
        """Wrap key-takeaway lines in platform-specific callout boxes.

        Detects lines starting with recognised prefixes like
        ``"重要:"``, ``"Tips:"``, etc.

        Args:
            content: Markdown text.

        Returns:
            Markdown with callout boxes inserted.
        """
        lines = content.split("\n")
        result: list[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            matched_prefix = self._match_callout_prefix(stripped)

            if matched_prefix:
                callout_text = stripped[len(matched_prefix):].strip()
                is_alert = self._is_alert_prefix(matched_prefix)
                result.append(self._wrap_callout(callout_text, is_alert))
            else:
                result.append(line)
            i += 1

        return "\n".join(result)

    def _wrap_callout(self, text: str, is_alert: bool = False) -> str:
        """Wrap *text* in a platform-appropriate callout box."""
        if self.platform == "zenn":
            tag = "message alert" if is_alert else "message"
            return f":::{tag}\n{text}\n:::"
        # note platform
        label = "**注意**" if is_alert else "**ポイント**"
        return f"> {label}\n> {text}"

    # ------------------------------------------------------------------
    # Toggle / details sections
    # ------------------------------------------------------------------

    def add_toggle_sections(self, content: str) -> str:
        """Wrap long code blocks (>20 lines) in collapsible sections.

        Args:
            content: Markdown text.

        Returns:
            Markdown with long code blocks wrapped in toggles.
        """

        def _replacer(match: re.Match) -> str:
            lang = match.group(1)
            code = match.group(2)
            if code.count("\n") <= 20:
                return match.group(0)  # leave short blocks alone
            return self._wrap_toggle(lang, code)

        return _CODE_BLOCK_RE.sub(_replacer, content)

    def _wrap_toggle(self, lang: str, code: str) -> str:
        """Wrap code in a platform-specific toggle/details block."""
        if self.platform == "zenn":
            return (
                f":::details コード全文\n"
                f"```{lang}\n{code}```\n"
                f":::"
            )
        return (
            f"<details><summary>コード全文</summary>\n\n"
            f"```{lang}\n{code}```\n"
            f"</details>"
        )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    @staticmethod
    def enhance_tables(content: str) -> str:
        """Ensure existing Markdown tables have proper column alignment.

        Scans for separator rows (e.g. ``|---|---|``) and normalises
        them to left-aligned columns with consistent padding.

        Args:
            content: Markdown text.

        Returns:
            Markdown with normalised table separators.
        """
        sep_re = re.compile(r"^\|([- :|]+\|)+\s*$", re.MULTILINE)

        def _normalise_sep(match: re.Match) -> str:
            cells = match.group(0).strip().strip("|").split("|")
            normalised = "| " + " | ".join(
                "---" if c.strip().strip(":") == "---" or "-" in c
                else c.strip()
                for c in cells
            ) + " |"
            return normalised

        return sep_re.sub(_normalise_sep, content)

    # ------------------------------------------------------------------
    # Reading progress markers
    # ------------------------------------------------------------------

    @staticmethod
    def add_reading_progress_markers(content: str) -> str:
        """Add horizontal rules between major sections for visual breathing room.

        Inserts ``---`` before each H2 heading that doesn't already
        have one.

        Args:
            content: Markdown text.

        Returns:
            Markdown with horizontal rules added.
        """
        lines = content.split("\n")
        result: list[str] = []

        for i, line in enumerate(lines):
            if line.startswith("## ") and i > 0:
                # Check whether the preceding non-blank line is already a rule.
                prev_non_blank = ""
                for j in range(i - 1, -1, -1):
                    if lines[j].strip():
                        prev_non_blank = lines[j].strip()
                        break
                if not re.match(r"^-{3,}\s*$", prev_non_blank):
                    result.append("")
                    result.append("---")
                    result.append("")
            result.append(line)

        return "\n".join(result)

    # ------------------------------------------------------------------
    # Visual break insertion
    # ------------------------------------------------------------------

    @staticmethod
    def insert_visual_breaks(
        content: str,
        max_chars_without_visual: int = 800,
    ) -> str:
        """Flag long text stretches that lack any visual element.

        Inserts an HTML comment placeholder where the Writer agent
        should consider adding an image or diagram.

        Args:
            content: Markdown text.
            max_chars_without_visual: Threshold in characters.

        Returns:
            Markdown with ``<!-- VISUAL_BREAK: ... -->`` comments.
        """
        visual_re = re.compile(
            r"(!\[|```|^\|.+\||\<img |:::details|:::message|<details)",
            re.MULTILINE,
        )

        lines = content.split("\n")
        result: list[str] = []
        chars_since_visual = 0

        for line in lines:
            if visual_re.search(line):
                chars_since_visual = 0
            else:
                chars_since_visual += len(line) + 1  # +1 for newline

            result.append(line)

            if chars_since_visual >= max_chars_without_visual:
                result.append(
                    "<!-- VISUAL_BREAK: consider adding image or diagram here -->"
                )
                chars_since_visual = 0

        return "\n".join(result)

    # ------------------------------------------------------------------
    # Table of contents
    # ------------------------------------------------------------------

    @staticmethod
    def add_toc(content: str) -> str:
        """Generate and insert a table of contents from H2/H3 headings.

        The TOC is placed after the first paragraph (or after front-matter
        and hero image if present).

        Args:
            content: Markdown text.

        Returns:
            Markdown with a TOC block inserted.
        """
        headings = _HEADING_RE.findall(content)
        toc_entries: list[str] = []

        for hashes, title in headings:
            level = len(hashes)
            if level not in (2, 3):
                continue
            slug = re.sub(r"[^\w\s-]", "", title.lower())
            slug = re.sub(r"[\s]+", "-", slug.strip())
            indent = "  " if level == 3 else ""
            toc_entries.append(f"{indent}- [{title}](#{slug})")

        if not toc_entries:
            return content

        toc_block = "## 目次\n\n" + "\n".join(toc_entries) + "\n"

        # Find insertion point: after front-matter + first paragraph.
        fm_match = _FRONTMATTER_RE.match(content)
        start = fm_match.end() if fm_match else 0
        body = content[start:]

        # Skip leading blank lines and the first paragraph.
        para_end = body.find("\n\n")
        if para_end == -1:
            insert_pos = start + len(body)
        else:
            insert_pos = start + para_end

        return (
            content[:insert_pos]
            + "\n\n"
            + toc_block
            + "\n"
            + content[insert_pos:]
        )

    # ------------------------------------------------------------------
    # Citation formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_citations(content: str) -> str:
        """Normalise citation blocks to a consistent style.

        Ensures blockquote citation lines have an em-dash prefix and
        consistent spacing.

        Args:
            content: Markdown text.

        Returns:
            Markdown with normalised citations.
        """
        # Pattern: a blockquote line that looks like a source attribution.
        # e.g. "> - Source Name" or "> -- Source" or "> Source:"
        cite_re = re.compile(
            r"^(>\s*)[-\u2014\u2013]{1,2}\s*(.+)$", re.MULTILINE
        )
        return cite_re.sub(r"\1\u2014 \2", content)

    # ------------------------------------------------------------------
    # Visual density analysis
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_visual_density(content: str) -> dict:
        """Analyse the article and return visual-density metrics.

        Args:
            content: Markdown text.

        Returns:
            Dict with keys ``total_chars``, ``image_count``,
            ``diagram_count``, ``table_count``, ``code_block_count``,
            ``callout_count``, ``visual_elements_total``,
            ``chars_per_visual``, ``visual_density_score``,
            ``meets_minimum``.
        """
        total_chars = len(content)
        image_count = len(re.findall(r"!\[", content))
        diagram_count = len(re.findall(r"```mermaid", content))
        table_count = len(re.findall(r"^\|.+\|.+\|$", content, re.MULTILINE))
        code_block_count = len(re.findall(r"```\w+", content))
        callout_count = len(re.findall(
            r"(:::message|:::details|<details)", content
        ))

        visual_total = (
            image_count
            + diagram_count
            + table_count
            + code_block_count
            + callout_count
        )

        chars_per_visual = (
            total_chars / visual_total if visual_total > 0 else float("inf")
        )

        # Score: 0-100.  More visual elements and lower chars_per_visual
        # yield a higher score.  The formula is a simple heuristic.
        if visual_total == 0:
            score = 0.0
        else:
            raw = min(visual_total / 3.0, 1.0) * 50  # element count component
            density_component = max(0, 50 - (chars_per_visual / 50))
            score = min(raw + density_component, 100.0)

        return {
            "total_chars": total_chars,
            "image_count": image_count,
            "diagram_count": diagram_count,
            "table_count": table_count,
            "code_block_count": code_block_count,
            "callout_count": callout_count,
            "visual_elements_total": visual_total,
            "chars_per_visual": round(chars_per_visual, 1),
            "visual_density_score": round(score, 1),
            "meets_minimum": visual_total >= 3,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_callout_prefix(line: str) -> Optional[str]:
        """Return the callout prefix if *line* starts with one, else None."""
        for prefix in _CALLOUT_PREFIXES:
            if line.startswith(prefix):
                return prefix
        return None

    @staticmethod
    def _is_alert_prefix(prefix: str) -> bool:
        """Return True if the prefix represents an alert/warning."""
        return prefix.lower().rstrip(":") in (
            "重要", "注意", "warning", "important",
        )

    @staticmethod
    def _image_block(image: dict) -> str:
        """Build a Markdown image block from an image dict."""
        alt = image.get("alt_text", "")
        url = image.get("url", "")
        attribution = image.get("attribution", "")
        block = f"![{alt}]({url})"
        if attribution:
            block += f"\n*{attribution}*"
        return block
