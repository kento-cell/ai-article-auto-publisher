"""Content converter for note.com publishing.

Converts Mermaid diagrams and Markdown tables to PNG images, since
note.com does not natively support either format.

Dependencies:
    - mmdc (Mermaid CLI) for diagram rendering
    - Playwright (chromium) for table screenshot rendering
"""

import logging
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Regex to match ```mermaid code blocks
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)

# Regex to match markdown tables (header + separator + body rows)
_TABLE_RE = re.compile(
    r"((?:^[ \t]*\|.+\|[ \t]*\n)"     # header row
    r"(?:^[ \t]*\|[-:| ]+\|[ \t]*\n)"  # separator row
    r"(?:^[ \t]*\|.+\|[ \t]*\n?)+)",   # body rows
    re.MULTILINE,
)

# HTML template for rendering tables as screenshots
_TABLE_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    margin: 0;
    padding: 16px;
    background: #ffffff;
    font-family: "Segoe UI", "Hiragino Sans", "Meiryo", sans-serif;
    font-size: 15px;
    color: #333;
}}
table {{
    border-collapse: collapse;
    width: auto;
}}
th, td {{
    border: 1px solid #d0d0d0;
    padding: 10px 16px;
    text-align: left;
    white-space: nowrap;
}}
th {{
    background-color: #f5f5f5;
    font-weight: 600;
}}
tr:nth-child(even) td {{
    background-color: #fafafa;
}}
</style>
</head>
<body>
{table_html}
</body>
</html>
"""


class NoteContentConverter:
    """Convert Mermaid diagrams and tables to images for note.com.

    Images are saved to ``data/images/`` and the original Markdown
    elements are replaced with ``![...](path)`` references.
    """

    def __init__(self, image_dir: str | Path | None = None) -> None:
        self._image_dir = Path(image_dir) if image_dir else Path("data/images")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert(self, markdown: str, slug: str) -> str:
        """Convert mermaid diagrams and tables to images for note.com.

        Args:
            markdown: Original Markdown content.
            slug: Article slug used for naming image files.

        Returns:
            Modified Markdown with image references replacing
            mermaid blocks and tables.
        """
        self._image_dir.mkdir(parents=True, exist_ok=True)

        markdown = self._convert_mermaid_blocks(markdown, slug)
        markdown = self._convert_tables(markdown, slug)
        return markdown

    # ------------------------------------------------------------------
    # Mermaid conversion
    # ------------------------------------------------------------------

    def _convert_mermaid_blocks(self, markdown: str, slug: str) -> str:
        """Replace all mermaid code blocks with rendered PNG images."""
        blocks = _MERMAID_BLOCK_RE.findall(markdown)
        if not blocks:
            return markdown

        result = markdown
        for idx, mermaid_code in enumerate(blocks, start=1):
            filename = f"{slug}_mermaid_{idx}.png"
            out_path = self._image_dir / filename

            try:
                self._render_mermaid_to_png(mermaid_code.strip(), out_path)
                image_ref = f"![diagram {idx}]({out_path.as_posix()})"
                # Replace the first remaining mermaid block
                result = _MERMAID_BLOCK_RE.sub(image_ref, result, count=1)
                logger.info("Mermaid block %d -> %s", idx, out_path)
            except Exception:
                logger.warning(
                    "Mermaid block %d conversion failed; keeping original",
                    idx,
                    exc_info=True,
                )

        return result

    @staticmethod
    def _find_mmdc() -> str:
        """Locate the mmdc executable, preferring .cmd on Windows."""
        if platform.system() == "Windows":
            cmd_path = shutil.which("mmdc.cmd") or shutil.which("mmdc")
        else:
            cmd_path = shutil.which("mmdc")
        if cmd_path is None:
            raise RuntimeError("mmdc not found on PATH")
        return cmd_path

    def _render_mermaid_to_png(self, mermaid_code: str, output_path: Path) -> None:
        """Render mermaid source to a PNG file using mmdc CLI."""
        mmdc = self._find_mmdc()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mmd", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(mermaid_code)
            tmp_path = Path(tmp.name)

        try:
            proc = subprocess.run(
                [
                    mmdc,
                    "-i", str(tmp_path),
                    "-o", str(output_path),
                    "-b", "white",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"mmdc failed (rc={proc.returncode}): {proc.stderr}")
        finally:
            tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Table conversion
    # ------------------------------------------------------------------

    def _convert_tables(self, markdown: str, slug: str) -> str:
        """Replace all markdown tables with rendered PNG images."""
        tables = _TABLE_RE.findall(markdown)
        if not tables:
            return markdown

        result = markdown
        for idx, table_md in enumerate(tables, start=1):
            filename = f"{slug}_table_{idx}.png"
            out_path = self._image_dir / filename

            try:
                self._render_table_to_png(table_md.strip(), out_path)
                image_ref = f"![table {idx}]({out_path.as_posix()})"
                result = result.replace(table_md, image_ref + "\n", 1)
                logger.info("Table %d -> %s", idx, out_path)
            except Exception:
                logger.warning(
                    "Table %d conversion failed; keeping original",
                    idx,
                    exc_info=True,
                )

        return result

    def _render_table_to_png(self, table_md: str, output_path: Path) -> None:
        """Render a markdown table to a PNG screenshot using Playwright."""
        html_table = self._markdown_table_to_html(table_md)
        full_html = _TABLE_HTML_TEMPLATE.format(table_html=html_table)

        # Write HTML to a temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(full_html)
            tmp_path = Path(tmp.name)

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(tmp_path.as_uri())
                # Screenshot just the body to get a tight crop
                body = page.locator("body")
                body.screenshot(path=str(output_path))
                browser.close()
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _markdown_table_to_html(table_md: str) -> str:
        """Convert a simple markdown table string to an HTML <table>."""
        lines = [
            line.strip()
            for line in table_md.strip().splitlines()
            if line.strip()
        ]
        if len(lines) < 2:
            return f"<pre>{table_md}</pre>"

        def parse_row(line: str) -> list[str]:
            # Strip leading/trailing pipes, split by pipe
            stripped = line.strip().strip("|")
            return [cell.strip() for cell in stripped.split("|")]

        header_cells = parse_row(lines[0])
        # lines[1] is the separator row — skip it
        body_rows = [parse_row(line) for line in lines[2:]]

        parts: list[str] = ["<table>", "<thead><tr>"]
        for cell in header_cells:
            parts.append(f"<th>{cell}</th>")
        parts.append("</tr></thead>")
        parts.append("<tbody>")
        for row in body_rows:
            parts.append("<tr>")
            for cell in row:
                parts.append(f"<td>{cell}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
        return "\n".join(parts)
