"""Mermaid diagram extraction, rendering, and embedding.

Extracts Mermaid code blocks from Markdown, renders them to SVG via the
Mermaid CLI (``mmdc``) or an online renderer, and replaces the original
code blocks with image references.

Dependencies: requests (for online fallback), subprocess (for mmdc)
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

MERMAID_BLOCK_RE = re.compile(
    r"```mermaid\s*\n(.*?)```", re.DOTALL
)
MERMAID_INK_URL = "https://mermaid.ink/svg"


class DiagramGenerator:
    """Render Mermaid diagrams to SVG and embed them in Markdown.

    The class first tries the local ``mmdc`` CLI (from
    ``@mermaid-js/mermaid-cli``).  If that is not installed it falls
    back to the public mermaid.ink online renderer.

    Attributes:
        use_cli: Whether the local CLI is available.
    """

    def __init__(self) -> None:
        """Detect available rendering backends."""
        self.use_cli: bool = shutil.which("mmdc") is not None
        if self.use_cli:
            logger.info("Mermaid CLI (mmdc) detected; will use local rendering.")
        else:
            logger.warning(
                "mmdc not found. Mermaid blocks will be kept as-is. "
                "Online rendering disabled to prevent content leakage."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_mermaid_blocks(self, markdown: str) -> List[str]:
        """Return all Mermaid code blocks found in *markdown*.

        Args:
            markdown: Full Markdown text.

        Returns:
            List of Mermaid diagram source strings (without the
            surrounding back-tick fences).
        """
        blocks = MERMAID_BLOCK_RE.findall(markdown)
        logger.debug("Extracted %d Mermaid block(s).", len(blocks))
        return [b.strip() for b in blocks]

    def render_to_svg(
        self,
        mermaid_code: str,
        output_path: str,
    ) -> str:
        """Render a single Mermaid diagram to an SVG file.

        Args:
            mermaid_code: The Mermaid source.
            output_path: Destination file path (should end in ``.svg``).

        Returns:
            The absolute path to the written SVG file.

        Raises:
            RuntimeError: If rendering fails via both backends.
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if self.use_cli:
            return self._render_via_cli(mermaid_code, output_path)
        raise RuntimeError(
            "No local Mermaid renderer (mmdc) available. "
            "Online rendering is disabled to prevent content leakage."
        )

    def embed_diagrams(
        self,
        markdown: str,
        output_dir: str,
        base_name: str = "diagram",
    ) -> str:
        """Replace Mermaid code blocks in *markdown* with image references.

        Each block is rendered to SVG inside *output_dir* and replaced
        by a Markdown image link ``![diagram](path)``.

        Args:
            markdown: Original Markdown text.
            output_dir: Directory to store generated SVG files.
            base_name: Filename prefix for the generated images.

        Returns:
            The updated Markdown with image references.
        """
        blocks = self.extract_mermaid_blocks(markdown)
        if not blocks:
            logger.info("No Mermaid blocks to embed.")
            return markdown

        result = markdown
        for idx, block in enumerate(blocks, start=1):
            filename = f"{base_name}_{idx}.svg"
            svg_path = os.path.join(output_dir, filename)

            try:
                self.render_to_svg(block, svg_path)
                image_ref = f"![{base_name} {idx}]({svg_path})"
            except RuntimeError:
                logger.warning("Diagram %d: keeping Mermaid code block (no local renderer).", idx)
                continue  # Don't replace, keep original

            # Replace the first remaining mermaid block.
            result = MERMAID_BLOCK_RE.sub(image_ref, result, count=1)

        logger.info("Embedded %d diagram(s) into Markdown.", len(blocks))
        return result

    # ------------------------------------------------------------------
    # Internal rendering backends
    # ------------------------------------------------------------------

    def _render_via_cli(self, mermaid_code: str, output_path: str) -> str:
        """Render using the local ``mmdc`` command."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mmd", delete=False
        ) as tmp:
            tmp.write(mermaid_code)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ["mmdc", "-i", tmp_path, "-o", output_path, "-b", "transparent"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error("mmdc stderr: %s", result.stderr)
                raise RuntimeError(f"mmdc failed: {result.stderr}")
            logger.debug("Rendered SVG via CLI -> %s", output_path)
            return os.path.abspath(output_path)
        finally:
            os.unlink(tmp_path)

    # _render_via_ink removed: online rendering disabled to prevent
    # leaking potentially sensitive article content to external services.
