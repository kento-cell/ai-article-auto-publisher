"""Retrofit affiliate links into existing Zenn articles.

Walks ``$ZENN_REPO_PATH/articles/*.md``, detects the article genre from the
title+body, and appends the matching affiliate section (``## 関連リンク``)
using the same :class:`AffiliateInjector` used by the main publishing
pipeline.  Idempotent: files that already contain a ``## 関連リンク``
heading are skipped.

Usage::

    # Dry-run (default) — prints what would change, writes nothing
    python scripts/retrofit_zenn_affiliates.py

    # Actually write files
    python scripts/retrofit_zenn_affiliates.py --apply

    # Write + git commit + push
    python scripts/retrofit_zenn_affiliates.py --apply --commit

Safety guarantees:
- YAML frontmatter is preserved byte-for-byte. CRLF/LF line endings and a
  UTF-8 BOM, if any, are preserved. Unterminated frontmatter is an error.
- Files already containing a ``## 関連リンク`` heading line are skipped.
  ``AffiliateInjector`` will refuse to double-inject as a second line of
  defence.
- Default mode is dry-run; ``--apply`` is required to touch the filesystem.
- ``--commit`` is opt-in, requires ``--apply``, and is aborted if any per-
  file error occurred during the write pass.
- Symlinks inside ``articles/`` are rejected.
- Any per-file error causes a non-zero process exit code even in dry-run.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# Ensure repo root is on sys.path so ``generators.*`` imports resolve
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from generators.affiliate_injector import AffiliateInjector  # noqa: E402

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("retrofit_zenn")

_FRONTMATTER_DELIM = "---"
_BOM = "\ufeff"
# Match a standalone "## 関連リンク" heading line (allow trailing whitespace
# and both half-width and full-width space after ##).
_AFFILIATE_HEADING_RE = re.compile(r"(?m)^##[ \t\u3000]+関連リンク\s*$")


def _read_file(path: Path) -> tuple[str, str, bool]:
    """Read *path* preserving newline style and BOM.

    Returns:
        (text, newline, had_bom)
        text: Decoded text with BOM stripped and line endings normalised to
              ``\\n``. Useful for parsing.
        newline: The detected newline style — ``"\\r\\n"`` if any CRLF was
                 present, otherwise ``"\\n"``.
        had_bom: True if the original file began with a UTF-8 BOM.
    """
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    if had_bom:
        raw = raw[3:]
    text = raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    # Normalise for parsing; we reapply the original style on write
    normalised = text.replace("\r\n", "\n")
    return normalised, newline, had_bom


def _write_file(
    path: Path,
    text: str,
    newline: str,
    had_bom: bool,
) -> None:
    """Write *text* back to *path*, restoring newline style and BOM.

    The write is atomic within the same directory: we write to ``.tmp``
    then ``os.replace`` it over the target.
    """
    if newline != "\n":
        text = text.replace("\n", newline)
    data = text.encode("utf-8")
    if had_bom:
        data = b"\xef\xbb\xbf" + data
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _split_frontmatter(text: str) -> tuple[str, str, bool]:
    """Split normalised markdown text into (frontmatter_block, body, ok).

    The frontmatter block includes the closing ``---\\n``.  ``ok`` is
    False when frontmatter is expected (starts with ``---``) but the
    closing delimiter is missing — that is an error and the file must be
    left alone.  Files with no frontmatter at all return ``("", text, True)``.
    """
    # Require exact "---" at column 0 (no leading/trailing whitespace) for
    # both open and close, so that indented "---" inside a YAML block scalar
    # is not mistaken for the closing delimiter.
    lines = text.split("\n")
    if not lines or lines[0] != _FRONTMATTER_DELIM:
        return "", text, True
    for idx in range(1, len(lines)):
        if lines[idx] == _FRONTMATTER_DELIM:
            fm_lines = lines[: idx + 1]
            body_lines = lines[idx + 1 :]
            frontmatter = "\n".join(fm_lines) + "\n"
            body = "\n".join(body_lines)
            return frontmatter, body, True
    return "", text, False  # unterminated frontmatter


def _extract_title(frontmatter: str) -> str:
    """Extract ``title:`` value from frontmatter (best-effort)."""
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("title:"):
            value = stripped[len("title:") :].strip()
            if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
                value = value[1:-1]
            return value
    return ""


def _has_affiliate_heading(body: str) -> bool:
    """Return True if *body* contains a ``## 関連リンク`` heading line."""
    return bool(_AFFILIATE_HEADING_RE.search(body))


def _process_file(
    path: Path,
    articles_dir: Path,
    injector: AffiliateInjector,
) -> tuple[str, bytes | None, dict]:
    """Process a single markdown file.

    Returns:
        (status, new_bytes_or_none, meta)
        status: one of "ready", "skip-has-affiliates", "skip-empty",
                "skip-no-change", "skip-no-frontmatter",
                "error-symlink", "error-unterminated-frontmatter",
                "error-read", "error-inject-idempotent"
        meta: diagnostic dict (unused by caller today but handy for logs)
    """
    # Reject symlinks / reparse points to avoid writing outside articles_dir
    try:
        resolved = path.resolve(strict=True)
        articles_resolved = articles_dir.resolve(strict=True)
    except OSError as e:
        return "error-read", None, {"err": str(e)}
    if path.is_symlink():
        return "error-symlink", None, {}
    try:
        resolved.relative_to(articles_resolved)
    except ValueError:
        return "error-symlink", None, {"err": "outside articles_dir"}

    try:
        text, newline, had_bom = _read_file(path)
    except (OSError, UnicodeDecodeError) as e:
        logger.error("Cannot read %s: %s", path, e)
        return "error-read", None, {"err": str(e)}

    if not text.strip():
        return "skip-empty", None, {}

    frontmatter, body, ok = _split_frontmatter(text)
    if not ok:
        return "error-unterminated-frontmatter", None, {}

    # Zenn articles must have frontmatter. If missing, skip — we won't risk
    # mangling an unexpected file format.
    if not frontmatter:
        return "skip-no-frontmatter", None, {}

    if not body.strip():
        return "skip-empty", None, {}

    if _has_affiliate_heading(body):
        return "skip-has-affiliates", None, {}

    title = _extract_title(frontmatter)
    injected_body = injector.inject(body, title=title, platform="zenn")

    if injected_body == body:
        return "skip-no-change", None, {}

    # Defence-in-depth: the injector must have added the affiliate heading.
    # If it did not (e.g. config changed), bail out rather than writing
    # something unexpected.
    if not _has_affiliate_heading(injected_body):
        return "error-inject-idempotent", None, {}

    # Preserve the original file's terminal newline convention: if the file
    # ended with exactly one \n, ensure the new content does too. If the
    # file did not end with \n (rare), keep it that way.
    ended_with_newline = text.endswith("\n")
    new_text = frontmatter + injected_body
    if ended_with_newline and not new_text.endswith("\n"):
        new_text += "\n"
    elif not ended_with_newline and new_text.endswith("\n"):
        new_text = new_text.rstrip("\n")

    # Encode preserving newline style and BOM
    encoded = _encode_for_write(new_text, newline, had_bom)
    return "ready", encoded, {"newline": newline, "bom": had_bom}


def _encode_for_write(text: str, newline: str, had_bom: bool) -> bytes:
    if newline != "\n":
        text = text.replace("\n", newline)
    data = text.encode("utf-8")
    if had_bom:
        data = b"\xef\xbb\xbf" + data
    return data


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _run_git(repo: Path, *args: str) -> None:
    cmd = ["git", *args]
    logger.info("git %s", " ".join(args))
    subprocess.run(cmd, cwd=repo, check=True, capture_output=True, text=True)


_ERROR_STATUSES = {
    "error-read",
    "error-symlink",
    "error-unterminated-frontmatter",
    "error-write",
    "error-inject-idempotent",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the modified files. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="After --apply, stage modified files and git commit + push.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Override ZENN_REPO_PATH.",
    )
    args = parser.parse_args()

    if args.commit and not args.apply:
        parser.error("--commit requires --apply")

    # Strict env validation: refuse to fall back to the CWD.
    if args.repo is not None:
        repo_path = args.repo
    else:
        env_val = os.environ.get("ZENN_REPO_PATH", "").strip()
        if not env_val:
            logger.error("ZENN_REPO_PATH is not set")
            return 2
        repo_path = Path(env_val)

    if not repo_path.is_dir():
        logger.error("Repo path is not a directory: %s", repo_path)
        return 2
    if not (repo_path / ".git").exists():
        logger.error("Not a git repository (no .git): %s", repo_path)
        return 2

    articles_dir = repo_path / "articles"
    if not articles_dir.is_dir():
        logger.error("articles directory not found: %s", articles_dir)
        return 2

    injector = AffiliateInjector()
    if not injector._config:  # noqa: SLF001
        logger.error("Affiliate config is empty; aborting")
        return 2

    md_files = sorted(articles_dir.glob("*.md"))
    logger.info("Scanning %d article(s) in %s", len(md_files), articles_dir)

    modified_paths: list[Path] = []
    counts: dict[str, int] = {}

    for path in md_files:
        status, new_bytes, _meta = _process_file(path, articles_dir, injector)
        counts[status] = counts.get(status, 0) + 1
        rel = path.name

        if status == "ready":
            if args.apply and new_bytes is not None:
                try:
                    _atomic_write_bytes(path, new_bytes)
                    modified_paths.append(path)
                    logger.info("[WROTE] %s", rel)
                except OSError as e:
                    logger.error("Failed to write %s: %s", rel, e)
                    counts["error-write"] = counts.get("error-write", 0) + 1
                    counts["ready"] -= 1
            else:
                logger.info("[WOULD WRITE] %s", rel)
        elif status == "skip-has-affiliates":
            logger.info("[SKIP-EXISTING] %s", rel)
        elif status == "skip-no-change":
            logger.info("[SKIP-NO-MATCH] %s", rel)
        elif status == "skip-empty":
            logger.info("[SKIP-EMPTY] %s", rel)
        elif status == "skip-no-frontmatter":
            logger.info("[SKIP-NO-FRONTMATTER] %s", rel)
        elif status == "error-symlink":
            logger.error("[ERROR-SYMLINK] %s (refused)", rel)
        elif status == "error-unterminated-frontmatter":
            logger.error("[ERROR-UNTERMINATED-FM] %s", rel)
        elif status == "error-inject-idempotent":
            logger.error("[ERROR-INJECT-NOOP] %s (injector returned body without affiliate heading)", rel)
        elif status == "error-read":
            logger.error("[ERROR-READ] %s", rel)
        else:
            logger.error("[ERROR-UNKNOWN:%s] %s", status, rel)

    logger.info("Summary: %s", counts)

    error_count = sum(counts.get(k, 0) for k in _ERROR_STATUSES)

    if args.apply and args.commit:
        if error_count > 0:
            logger.error(
                "Aborting commit/push: %d error(s) during write pass", error_count
            )
            return 1
        if not modified_paths:
            logger.info("Nothing to commit")
        else:
            try:
                for p in modified_paths:
                    _run_git(repo_path, "add", str(p))
                _run_git(
                    repo_path,
                    "commit",
                    "-m",
                    f"chore: retrofit affiliate links into {len(modified_paths)} article(s)",
                )
                _run_git(repo_path, "push")
                logger.info("Pushed %d article(s) to remote", len(modified_paths))
            except subprocess.CalledProcessError as e:
                logger.error(
                    "git failed: %s\nstdout=%s\nstderr=%s", e, e.stdout, e.stderr
                )
                return 1

    if not args.apply and counts.get("ready", 0) > 0:
        logger.info(
            "Dry-run complete. Re-run with --apply to write %d file(s).",
            counts["ready"],
        )

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
