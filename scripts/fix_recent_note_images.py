"""Regenerate topical inline images for the latest ~10 note posts.

Motivation: inline images on recent note posts were all identical
"lifestyle" stock photos (see `_extract_image_query` fallback bug,
fixed in main.py 2026-04-19). This script:

  1. Fetches the user's last N posts from note.com's creator-content
     API to obtain URL + title + body snippet.
  2. For each post, matches the body to the stored
     `data/articles/note-*.json` (preferred, full content) or falls
     back to the API body snippet.
  3. Computes a topical Unsplash query via the already-fixed
     `_extract_image_query(title, content)`.
  4. Downloads 4 fresh images via `ImageSourcer` into
     `data/images/stock/`.
  5. Calls `NotePublisher.edit_article(url, new_content=<current body
     with local image markdown stripped>, inline_image_paths=[4 new
     local paths])`. The editor then re-hosts each image on
     assets.st-note.com and the live post shows topical photos
     instead of the generic 4 lifestyle shots it had before.

Run:
    venv/Scripts/python.exe scripts/fix_recent_note_images.py

Limit with --count N (default 10). Dry run with --dry-run.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

if sys.platform == "win32" and __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# Load .env so UNSPLASH_ACCESS_KEY etc. are available.
_ENV_FILE = _REPO / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            import os as _os
            _os.environ.setdefault(_k.strip(), _v.strip())

from generators.image_sourcer import ImageSourcer  # noqa: E402
from main import _download_image, _extract_image_query  # noqa: E402
from publishers.note_publisher import NotePublisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fix_recent_note_images")

NOTE_USER = "note-user"
NOTE_API_BASE = f"https://note.com/api/v2/creators/{NOTE_USER}/contents"
_LOCAL_IMG_RE = re.compile(
    r"!\[[^\]]*\]\((data/images/[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)


def _fetch_recent_posts(count: int) -> list[dict]:
    """Fetch the creator's recent published posts via note's public API."""
    posts: list[dict] = []
    page = 1
    while len(posts) < count and page <= 5:
        url = f"{NOTE_API_BASE}?kind=note&page={page}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 fix-note-images"})
        raw = urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        contents = (data.get("data") or {}).get("contents", [])
        for c in contents:
            if c.get("status") != "published":
                continue
            posts.append({
                "url": c.get("noteUrl", ""),
                "key": c.get("key", ""),
                "title": c.get("name", ""),
                "body_snippet": c.get("body", "") or "",
                "publish_at": c.get("publishAt", ""),
                "image_count": c.get("imageCount", 0),
            })
            if len(posts) >= count:
                break
        if (data.get("data") or {}).get("isLastPage"):
            break
        page += 1
    return posts[:count]


def _load_local_jsons() -> list[dict]:
    """Load every note article JSON on disk with its content."""
    out: list[dict] = []
    for p in sorted(
        (_REPO / "data" / "articles").glob("note-*.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    ):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "path": p,
                "title": d.get("title", ""),
                "content": d.get("content", ""),
            })
        except Exception as exc:
            logger.warning("Failed to read %s: %s", p.name, exc)
    return out


def _match_local(
    post_title: str, post_snippet: str, locals_: list[dict]
) -> dict | None:
    """Pick the local JSON whose title/content best matches the live post.

    Matching is done in three passes, most specific first:
      1. Live post title == local content's first line (the H1 baked
         into content usually equals the published title).
      2. Local JSON title is a substring of post title or snippet —
         covers the case where the JSON title is the raw trend topic
         ("森英恵") but the published title references the rewritten
         subject ("韓国Ulala…").
      3. Fuzzy similarity on title pair — last-resort tie-breaker.
    """
    best: tuple[float, dict | None] = (0.0, None)
    haystack = (post_title + "\n" + (post_snippet or "")).strip()
    for loc in locals_:
        loc_title = loc["title"] or ""
        loc_content = loc["content"] or ""
        # --- 1. First-line of stored content vs live title (strongest) ---
        first_line = loc_content.splitlines()[0].strip() if loc_content else ""
        if first_line and post_title:
            # Published title may be truncated in the API response, so
            # check both directions.
            if (first_line[:40] and first_line[:40] in post_title) or (
                post_title[:40] and post_title[:40] in first_line
            ):
                score = 2.0 + len(first_line) / 200.0
                if score > best[0]:
                    best = (score, loc)
                continue
        # --- 2. Short JSON title appears inside live post text ---
        if loc_title and loc_title in haystack:
            score = 1.0 + len(loc_title) / 100.0
        else:
            # --- 3. Fuzzy fallback ---
            score = SequenceMatcher(
                None, post_title[:60], loc_title[:60]
            ).ratio()
        if score > best[0]:
            best = (score, loc)
    if best[0] >= 0.45 and best[1] is not None:
        return best[1]
    return None


def _strip_local_images_markdown(content: str) -> str:
    """Drop every ``![...](data/images/...)`` line from stored content.

    Those references point to disk paths that no longer resolve once
    note republishes; we are about to upload fresh images inline.
    """
    return re.sub(r"\n?!\[[^\]]*\]\(data/images/[^)\s]+(?:\s+\"[^\"]*\")?\)\n?",
                  "\n", content)


def _download_topical_images(
    title: str, content: str, slug: str, count: int = 4
) -> list[Path]:
    """Use the fixed _extract_image_query to pull N topical Unsplash shots."""
    query = _extract_image_query(title, content)
    logger.info("  query=%r  (for %s)", query, title[:40])
    sourcer = ImageSourcer()
    images = sourcer.find_images(query, count=count)
    usable = [
        img for img in images
        if img.get("url") and img.get("platform") != "Placeholder"
    ]
    if not usable:
        logger.warning("  no usable images for query %r", query)
        return []

    out_dir = _REPO / "data" / "images" / "stock"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)[:40]
    paths: list[Path] = []
    for idx, img in enumerate(usable[:count]):
        dest = out_dir / f"{safe_slug}_fix_{idx}.jpg"
        if dest.exists() and dest.stat().st_size > 0:
            paths.append(dest)
            continue
        url = img.get("url") or img.get("download_url", "")
        local = _download_image(url, dest)
        if local is not None:
            paths.append(local)
    return paths


def _build_fresh_body(content: str) -> str:
    """Return content with stock-image markdown removed so the editor
    paste leaves only prose + headings + links."""
    return _strip_local_images_markdown(content)


_LIVE_BODY_MAX_BYTES = 4 * 1024 * 1024  # 4 MiB cap on scraped HTML


def _fetch_live_body(url: str) -> str:
    """Fallback: scrape the live note article body if no local JSON matches.

    SSRF guard: ``url`` comes from the note v2 creator API response, but
    that is still attacker-influenced from the perspective of a malicious
    article-listing crawl — refuse anything that is not ``https://note.com``
    or a direct note subdomain, and cap the response size.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or not (
        parsed.hostname == "note.com"
        or (parsed.hostname or "").endswith(".note.com")
    ):
        logger.warning("  live fetch rejected — host %s", parsed.hostname)
        return ""
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 fix-note-images/1.0",
        })
        with urlopen(req, timeout=30) as resp:
            raw = resp.read(_LIVE_BODY_MAX_BYTES + 1)
        if len(raw) > _LIVE_BODY_MAX_BYTES:
            logger.warning("  live fetch rejected — body > %d bytes",
                           _LIVE_BODY_MAX_BYTES)
            return ""
        html = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("  live fetch failed: %s", exc)
        return ""
    # Strip <script>/<style> first so JSON-LD doesn't leak into the body.
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    article = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
    body = article.group(1) if article else html
    # Drop tags, keep text — crude but adequate for image-query heuristic.
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"&nbsp;|&amp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logger.info("Fetching the last %d note posts …", args.count)
    posts = _fetch_recent_posts(args.count)
    logger.info("Got %d posts.", len(posts))

    locals_ = _load_local_jsons()
    logger.info("Loaded %d local note JSON files.", len(locals_))

    jobs: list[dict] = []
    for post in posts:
        match = _match_local(post["title"], post["body_snippet"], locals_)
        if match:
            logger.info(
                "[MATCH] %s  ⇄  %s (%s)",
                post["title"][:50], match["title"][:40], match["path"].name,
            )
            content = match["content"]
            source = "local_json"
        else:
            logger.info("[LIVE]  %s  (no local match, scraping page)",
                        post["title"][:50])
            content = _fetch_live_body(post["url"])
            source = "live"
        jobs.append({**post, "content": content, "source": source})

    if args.dry_run:
        logger.info("=== DRY RUN — queries only, no edits ===")
        for j in jobs:
            query = _extract_image_query(j["title"], j["content"])
            logger.info("  [%s] %s → query=%r",
                        j["source"], j["title"][:60], query)
        return 0

    pub = NotePublisher(headless=False)
    failures: list[str] = []
    try:
        for j in jobs:
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", j["key"] or j["title"])[:40]
            imgs = _download_topical_images(
                j["title"], j["content"], slug=slug, count=4,
            )
            if not imgs:
                logger.warning("Skip %s (no images)", j["url"])
                failures.append(j["url"] + " (no images)")
                continue

            fresh_body = _build_fresh_body(j["content"]) if j["content"] else None
            logger.info("Editing: %s", j["url"])
            try:
                ok = pub.edit_article(
                    url=j["url"],
                    new_title=None,          # keep existing
                    new_content=fresh_body,  # strip stale local ![...] refs
                    inline_image_paths=[str(p.resolve()) for p in imgs],
                )
            except Exception as exc:
                logger.error("edit_article raised: %s", exc)
                ok = False
            if not ok:
                failures.append(j["url"])
                continue
            time.sleep(4)
    finally:
        pub.close()

    if failures:
        logger.error("Failures: %s", failures)
        return 1
    logger.info("All %d posts updated.", len(jobs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
