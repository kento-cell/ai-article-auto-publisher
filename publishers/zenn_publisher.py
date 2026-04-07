"""Zenn article publisher via local Git repository.

Zenn publishes articles from a GitHub-connected repository.  This module
creates markdown files with the required frontmatter in the ``articles/``
directory of the local Zenn repo clone, then commits and pushes.
"""

import hashlib
import logging
import os
import re
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum number of topics Zenn allows per article.
_MAX_TOPICS = 5
# Maximum slug length (Zenn recommendation).
_MAX_SLUG_LENGTH = 50


class ZennPublisher:
    """Publish articles to Zenn by committing markdown to a Git repo.

    Args:
        repo_path: Absolute path to the local Zenn repo clone.
            Defaults to the ``ZENN_REPO_PATH`` environment variable.

    Raises:
        ValueError: If *repo_path* is not provided and the env var is unset.
        FileNotFoundError: If the resolved path does not exist.
    """

    def __init__(self, repo_path: str | None = None) -> None:
        resolved = repo_path or os.environ.get("ZENN_REPO_PATH")
        if not resolved:
            raise ValueError(
                "repo_path must be supplied or ZENN_REPO_PATH must be set"
            )
        self.repo_path = Path(resolved)
        if not self.repo_path.is_dir():
            raise FileNotFoundError(
                f"Zenn repo directory not found: {self.repo_path}"
            )
        self.articles_dir = self.repo_path / "articles"
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        logger.info("ZennPublisher initialised (repo=%s)", self.repo_path)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def create_article(
        self,
        title: str,
        content: str,
        topics: list[str],
        article_type: str = "tech",
    ) -> str:
        """Create a new Zenn article markdown file.

        Args:
            title: Article title.
            content: Markdown body.
            topics: List of topic tags (max 5).
            article_type: ``"tech"`` or ``"idea"``.

        Returns:
            The generated slug used as the filename stem.

        Raises:
            ValueError: If *topics* is empty or *article_type* is invalid.
        """
        if article_type not in ("tech", "idea"):
            raise ValueError(f"article_type must be 'tech' or 'idea', got {article_type!r}")
        if not topics:
            raise ValueError("At least one topic is required")

        slug = self._generate_slug(title)
        trimmed_topics = topics[:_MAX_TOPICS]
        frontmatter = self._build_frontmatter(
            title=title,
            topics=trimmed_topics,
            article_type=article_type,
        )
        file_path = self.articles_dir / f"{slug}.md"
        counter = 1
        while file_path.exists():
            file_path = self.articles_dir / f"{slug}-{counter}.md"
            counter += 1
        file_path.write_text(
            f"{frontmatter}\n{content}\n", encoding="utf-8"
        )
        logger.info("Article created: %s", file_path)
        return slug

    def publish(self, slug: str) -> bool:
        """Stage, commit, and push an article to the remote.

        Args:
            slug: The slug (filename stem) of the article to publish.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        file_path = self.articles_dir / f"{slug}.md"
        if not file_path.exists():
            logger.error("Article file not found: %s", file_path)
            return False

        # Flip frontmatter to published: true before committing
        try:
            text = file_path.read_text(encoding="utf-8")
            updated = re.sub(
                r"^published:\s*false\s*$",
                "published: true",
                text,
                flags=re.MULTILINE,
            )
            if updated != text:
                file_path.write_text(updated, encoding="utf-8")
                logger.info("Set published: true in %s", file_path.name)
        except OSError:
            logger.exception("Failed to update frontmatter for %s", slug)
            return False

        try:
            self._run_git("add", str(file_path))
            self._run_git(
                "commit", "-m", f"publish: {slug}"
            )
            self._run_git("push")
            logger.info("Article published: %s", slug)
            return True
        except subprocess.CalledProcessError:
            logger.exception("Git operation failed for slug '%s'", slug)
            return False

    def list_drafts(self) -> list[dict[str, str]]:
        """List unpublished articles (``published: false`` in frontmatter).

        Returns:
            List of dicts with ``slug`` and ``title`` keys.
        """
        drafts: list[dict[str, str]] = []
        for md_file in self.articles_dir.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                logger.warning("Cannot read %s", md_file)
                continue
            if self._is_draft(text):
                title = self._extract_title(text)
                drafts.append({"slug": md_file.stem, "title": title})
        logger.info("Found %d draft(s)", len(drafts))
        return drafts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_slug(title: str) -> str:
        """Create a URL-friendly slug from *title*.

        For non-ASCII titles (e.g. Japanese) where the ASCII transliteration
        is very short or empty, a hash suffix derived from the original title
        is appended to avoid slug collisions.

        Args:
            title: Human-readable article title.

        Returns:
            Lowercased, hyphen-separated ASCII slug with a date prefix.
        """
        normalised = unicodedata.normalize("NFKD", title)
        ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
        slug_body = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")

        # If ASCII body is empty/short (e.g. Japanese-only title), use hash
        if len(slug_body) < 4:
            title_hash = hashlib.md5(title.encode("utf-8")).hexdigest()[:8]
            slug_body = f"{slug_body}-{title_hash}" if slug_body else title_hash

        date_prefix = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        slug = f"{date_prefix}-{slug_body}"
        return slug[:_MAX_SLUG_LENGTH]

    @staticmethod
    def _build_frontmatter(
        title: str,
        topics: list[str],
        article_type: str,
    ) -> str:
        """Build Zenn YAML frontmatter block."""
        topics_yaml = ", ".join(f'"{t}"' for t in topics)
        return (
            "---\n"
            f'title: "{title}"\n'
            'emoji: "📝"\n'
            f'type: "{article_type}"\n'
            f"topics: [{topics_yaml}]\n"
            "published: false\n"
            "---\n"
        )

    @staticmethod
    def _is_draft(text: str) -> bool:
        """Return ``True`` if the article frontmatter has ``published: false``."""
        return bool(re.search(r"^published:\s*false\s*$", text, re.MULTILINE))

    @staticmethod
    def _extract_title(text: str) -> str:
        """Extract the title value from YAML frontmatter."""
        match = re.search(r'^title:\s*"(.+?)"\s*$', text, re.MULTILINE)
        return match.group(1) if match else "(untitled)"

    def _run_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run a git command inside the repo directory.

        Raises:
            subprocess.CalledProcessError: If the command exits non-zero.
        """
        cmd = ["git", *args]
        logger.debug("Running: %s", " ".join(cmd))
        return subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
