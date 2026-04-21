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

        # Zenn max title length is 70 chars
        if len(title) > 70:
            title = title[:67] + "..."
            logger.info("Title truncated to 70 chars: %s", title)

        # Sanitize Mermaid: fix invalid syntax from Gemma3
        # (e.g. D[出力 (3D)] — parens inside brackets break the parser)
        content = self._sanitize_mermaid_labels(content)

        # Localise inline stock photos: copy each referenced image
        # into the Zenn content repo under ``images/<slug>/`` and
        # rewrite the markdown to use ``/images/<slug>/…``. Zenn
        # silently replaces external (non-repo) image URLs with
        # ``error.svg``, so this repo-hosted path is the only way the
        # image actually renders on zenn.dev. Uses the slug about to
        # be generated below; re-compute it here so we have it before
        # writing the file.
        _slug_preview = self._generate_slug(title)
        content = self._localize_stock_images_for_zenn(content, _slug_preview)

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
            # Also stage any inline images this article copied into the
            # Zenn repo under images/<slug>/ — create_article's
            # _localize_stock_images_for_zenn placed them there.
            images_slug_dir = Path(self.repo_path) / "images" / slug
            if images_slug_dir.exists():
                self._run_git("add", str(images_slug_dir))
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
    def _sanitize_mermaid_labels(content: str) -> str:
        """Fix common Gemma3 mermaid syntax errors.

        Problems fixed:
        - D[出力 (3D)]: parens inside brackets → replaced with 全角
        - D[label "with" quotes]: quotes → removed
        """
        mermaid_re = re.compile(r"(```mermaid\s*\n)(.*?)(```)", re.DOTALL)

        def _fix_block(m: re.Match[str]) -> str:
            fence_start = m.group(1)
            body = m.group(2)
            fence_end = m.group(3)

            # In node labels [ ... ] or ( ... ), replace problematic chars
            def _fix_bracket(bm: re.Match[str]) -> str:
                label = bm.group(1)
                # Replace parens → 全角
                label = label.replace("(", "（").replace(")", "）")
                # Remove double quotes
                label = label.replace('"', "")
                return f"[{label}]"

            body = re.sub(r"\[([^\]]+)\]", _fix_bracket, body)
            return fence_start + body + fence_end

        return mermaid_re.sub(_fix_block, content)

    _STOCK_IMG_RE = re.compile(
        r'!\[([^\]]*)\]\(\s*(data/images/[^\s)]+)'
        r'(?:\s+"([^"]+)")?\s*\)',
    )

    def _localize_stock_images_for_zenn(
        self, content: str, slug: str
    ) -> str:
        """Copy Unsplash-origin stock photos into the Zenn content repo
        and rewrite markdown to use the repo-relative path.

        Zenn refuses external image URLs in markdown (they get replaced
        by ``error.svg`` server-side). Zenn does support images hosted
        inside the content repo at ``images/<slug>/filename.jpg``
        referenced as ``/images/<slug>/filename.jpg`` in the markdown.
        This helper:

          1. Walks every ``![alt](data/images/stock/x.jpg "https://…")``
             in *content*.
          2. For each match, downloads the title-attribute URL to
             ``<zenn_repo>/images/<slug>/<basename>`` (falls back to a
             local copy of the existing ``data/images/stock/...`` file
             if the URL is unreachable).
          3. Rewrites the markdown to ``![alt](/images/<slug>/<basename>)``.
          4. Returns the rewritten content. The caller still needs to
             ``git add images/<slug>/`` so the binary lands on the push.
        """
        import shutil as _shutil
        import requests as _requests
        from pathlib import Path as _Path
        from urllib.parse import urlparse as _urlparse

        # Allowlist mirrors ``main._IMAGE_HOST_ALLOWLIST`` — we refuse
        # to fetch from anywhere else because the URL comes from the
        # LLM-authored markdown (which an upstream prompt injection
        # could swing at an internal SSRF target).
        _HOST_ALLOW = {
            "images.unsplash.com", "plus.unsplash.com",
            "images.pexels.com", "www.pexels.com",
            "upload.wikimedia.org",
        }
        _MIME_ALLOW = {"image/jpeg", "image/png", "image/webp", "image/gif"}
        _MAX_BYTES = 10 * 1024 * 1024
        _EXT_ALLOW = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

        repo_root = _Path(self.repo_path)
        images_dir = (repo_root / "images" / slug).resolve()
        images_dir.mkdir(parents=True, exist_ok=True)

        # Pre-compute stock root once so each rewrite iteration can
        # validate the fallback candidate without re-resolving the
        # pipeline's CWD every call.
        _stock_root = (_Path.cwd() / "data" / "images" / "stock").resolve()

        def _download(url: str, dest: _Path) -> bool:
            parsed = _urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in _HOST_ALLOW:
                logger.warning(
                    "Zenn image download rejected — host %s not allowed",
                    parsed.hostname,
                )
                return False
            try:
                with _requests.get(
                    url, timeout=30, stream=True, allow_redirects=False,
                ) as resp:
                    if 300 <= resp.status_code < 400:
                        logger.warning(
                            "Zenn image download rejected — refusing redirect to %s",
                            resp.headers.get("Location", "<unknown>"),
                        )
                        return False
                    resp.raise_for_status()
                    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                    if ctype and ctype not in _MIME_ALLOW:
                        logger.warning(
                            "Zenn image download rejected — bad content-type %s", ctype,
                        )
                        return False
                    total = 0
                    chunks: list[bytes] = []
                    for chunk in resp.iter_content(65536):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > _MAX_BYTES:
                            logger.warning(
                                "Zenn image download rejected — exceeds %d bytes", _MAX_BYTES,
                            )
                            return False
                        chunks.append(chunk)
                dest.write_bytes(b"".join(chunks))
                return True
            except Exception as exc:
                logger.warning("Unsplash download failed (%s): %s", url, exc)
                return False

        def _rewrite(m: re.Match[str]) -> str:
            alt = m.group(1)
            local_path = m.group(2)
            url = (m.group(3) or "").strip()
            src_basename = _Path(local_path).name
            # Guard: basename must contain no directory components and
            # have an allowed extension. Defends against an LLM-emitted
            # reference like ``data/images/../../.env`` which would
            # otherwise produce a ``dest`` outside ``images_dir``.
            if "/" in src_basename or "\\" in src_basename or ".." in src_basename:
                return ""
            if _Path(src_basename).suffix.lower() not in _EXT_ALLOW:
                return ""
            dest = (images_dir / src_basename).resolve()
            if images_dir not in dest.parents and dest.parent != images_dir:
                logger.warning(
                    "Zenn image dest escapes images_dir: %s", dest,
                )
                return ""

            landed = False
            if url:
                landed = _download(url, dest)
            if not landed:
                # Fallback to the local stock file — but only if the
                # resolved source is inside the stock root and has an
                # image extension. A malicious reference to
                # ``data/images/../../.env`` would resolve outside and
                # be skipped here.
                try:
                    cand = (_Path.cwd() / local_path).resolve()
                except Exception:
                    cand = None
                if (
                    cand is not None
                    and (_stock_root in cand.parents or cand.parent == _stock_root)
                    and cand.suffix.lower() in _EXT_ALLOW
                    and cand.exists()
                    and cand.stat().st_size > 0
                ):
                    _shutil.copyfile(cand, dest)
                    landed = True
            if not landed:
                logger.warning(
                    "Could not localise image for %s — dropping reference", slug,
                )
                return ""

            safe_alt = alt.replace("[", "(").replace("]", ")")
            return f"![{safe_alt}](/images/{slug}/{src_basename})"

        rewritten = self._STOCK_IMG_RE.sub(_rewrite, content)
        rewritten = re.sub(r"\n{3,}", "\n\n", rewritten)
        return rewritten

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
