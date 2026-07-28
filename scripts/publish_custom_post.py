"""Publish a single hand-authored note post with topical Unsplash images.

Reads a JSON spec from ``data/custom_posts/*.json`` and:
  1. Downloads N topical images from Unsplash using *image_query*.
  2. Calls :meth:`NotePublisher.publish_article` which creates the new
     post, pastes the body HTML, uploads the inline images distributed
     across H2 sections (with the ``※イメージ画像`` figcaption), and
     publishes.
  3. Prints the published URL.

JSON schema::

    {
      "platform": "note",
      "title": "...",
      "image_query": "korea idol kpop",
      "content": "markdown body...",
      "tags": ["韓国コスメ", ...],
      "cover_image_query": "(optional; defaults to image_query)"
    }

Run:
    py scripts/publish_custom_post.py data/custom_posts/k_beauty_2026_spring.json
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
from pathlib import Path

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

_ENV_FILE = _REPO / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from generators.image_sourcer import ImageSourcer  # noqa: E402
from main import _download_image  # noqa: E402
from publishers.note_publisher import NotePublisher  # noqa: E402


_TOPIC_ALIGNED_TAGS: dict[str, list[str]] = {
    # Ordered most-specific → most-general. First-match wins so
    # medical posts are not tagged #韓国 via the generic beauty pool.
    # Each pattern is regex; each value is a curated high-reach tag
    # list scored against note's recent tag distribution.
    "医療|クリニック|皮膚科|エクソソーム|ダーマペン|脱毛": [
        "美容", "スキンケア", "自分磨き", "ライフスタイル",
        "エッセイ", "心理学", "生き方", "毎日note",
    ],
    "韓国|K-POP|アイドル|BTS|BLACKPINK|NewJeans": [
        "韓国", "美容", "スキンケア", "ライフスタイル",
        "エッセイ", "自分磨き", "心理学",
    ],
    "コスメ|美容|メイク|スキンケア|ダイエット|恋愛|ファッション|自分磨き": [
        "美容", "スキンケア", "ライフスタイル", "自分磨き",
        "エッセイ", "心理学", "生き方", "毎日note", "ダイエット",
    ],
    "仕事|副業|ビジネス|マネタイズ|起業|フリーランス|AI|ChatGPT|Claude": [
        "AI", "ChatGPT", "生成AI", "AI活用", "仕事", "ビジネス",
        "副業", "フリーランス", "働き方", "マーケティング",
    ],
}


def _blend_learned_tags(user_tags: list[str], limit: int = 10) -> list[str]:
    """Mix the user's topic-specific tags with learned high-reach tags
    relevant to the post's category.

    Without topic-alignment the blender dropped #AI and #仕事 onto a
    K-beauty article, which is worse than no blending. This version
    picks a curated subset of learned tags based on keyword overlap
    with the user-provided tags, then fills up to *limit*.
    """
    import re as _re
    knowledge = _REPO / "docs" / "knowledge" / "note-trends"

    # 1. Collect learned top tags from the latest report (fallback pool).
    learned: list[str] = []
    if knowledge.exists():
        reports = sorted(knowledge.glob("*_auto_learning.md"), reverse=True)
        if reports:
            text = reports[0].read_text(encoding="utf-8")
            in_tag_section = False
            for line in text.splitlines():
                if line.startswith("## タグ分布"):
                    in_tag_section = True
                    continue
                if in_tag_section:
                    if line.startswith("## "):
                        break
                    m = _re.match(
                        r"-\s*#?([^\s:：]+)\s*[:：]\s*\d+", line,
                    )
                    if m:
                        learned.append(m.group(1).lstrip("#"))

    # 2. Pick a topic-aligned curated list by matching user_tags against
    # _TOPIC_ALIGNED_TAGS. First match wins — the dict is ordered most
    # specific → most general so medical/clinic pattern is checked
    # before the generic beauty pattern, which would otherwise overlap
    # on user_tags containing 「美容」 and pollute medical posts with
    # #韓国.
    user_blob = "|".join(user_tags)
    preferred: list[str] = []
    for pattern, curated in _TOPIC_ALIGNED_TAGS.items():
        if _re.search(pattern, user_blob, _re.IGNORECASE):
            preferred = list(curated)
            break
    # Intersect preferred with learned (only use tags that are BOTH
    # topically aligned AND actually popular on note). If the
    # intersection is empty, fall back to the preferred list directly.
    learned_set = set(learned)
    preferred_and_popular = [t for t in preferred if t in learned_set]
    if not preferred_and_popular:
        preferred_and_popular = preferred

    # 3. Merge: user_tags first (preserve intent), then preferred.
    seen: set[str] = set()
    blended: list[str] = []
    for t in list(user_tags) + preferred_and_popular:
        key = t.strip().lstrip("#").lower()
        if key and key not in seen:
            seen.add(key)
            blended.append(t.strip().lstrip("#"))
        if len(blended) >= limit:
            break
    return blended

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("publish_custom_post")


# Image-cascade helpers moved to generators/chatgpt_batch_helper.py
# so main.py's _publish_note can share the exact same logic. Local
# wrapper preserves the old call sites in this file.
from generators.chatgpt_batch_helper import (
    chatgpt_image_batch as _chatgpt_image_batch,
    is_brave_running as _is_brave_running,  # noqa: F401  (legacy alias)
)


def _download_images(query: str, slug: str, count: int) -> list[Path]:
    sourcer = ImageSourcer()
    results = sourcer.find_images(query, count=count * 2)  # over-fetch for safety
    usable = [
        img for img in results
        if img.get("url") and img.get("platform") != "Placeholder"
    ]
    if not usable:
        logger.warning("no usable images for query %r", query)
        return []

    out_dir = _REPO / "data" / "images" / "stock"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)[:40]
    paths: list[Path] = []
    for idx, img in enumerate(usable[:count]):
        dest = out_dir / f"{safe_slug}_custom_{idx}.jpg"
        if dest.exists() and dest.stat().st_size > 0:
            paths.append(dest)
            continue
        url = img.get("url") or img.get("download_url", "")
        local = _download_image(url, dest)
        if local is not None:
            paths.append(local)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", help="Path to JSON spec file")
    parser.add_argument("--inline-count", type=int, default=4)
    parser.add_argument(
        "--price", type=int, default=None,
        help="Override price in yen (defaults to spec.price or 0)",
    )
    args = parser.parse_args()

    spec_path = Path(args.spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    title = spec["title"]
    content = spec["content"]
    query = spec.get("image_query", "lifestyle")
    cover_query = spec.get("cover_image_query", query)
    tags = _blend_learned_tags(spec.get("tags", []), limit=10)
    logger.info("Tags (blended with learned): %s", tags)
    slug_hint = re.sub(r"[^a-zA-Z0-9_]", "_", spec_path.stem)[:40]

    logger.info("Title: %s", title[:80])
    logger.info("Image query: %r (cover: %r)", query, cover_query)

    # ----------------------------------------------------------------
    # Image cascade: ChatGPT (default ON, set USE_CHATGPT_IMAGES=0 to
    # disable) → Unsplash → fail
    # ----------------------------------------------------------------
    cover: str | None = None
    inline_paths: list[Path] = []
    from generators.chatgpt_batch_helper import is_chatgpt_image_gen_enabled
    use_chatgpt = is_chatgpt_image_gen_enabled()

    if use_chatgpt:
        chatgpt_cover, chatgpt_inline = _chatgpt_image_batch(
            title=title,
            content=content,
            inline_count=args.inline_count,
            slug_hint=slug_hint,
            genre_hint=spec.get("image_query", "general tech / lifestyle"),
        )
        if chatgpt_cover and len(chatgpt_inline) >= args.inline_count:
            cover = str(chatgpt_cover.resolve())
            inline_paths = chatgpt_inline
            logger.info("✓ Using ChatGPT-generated images (full set).")
        else:
            logger.warning(
                "ChatGPT image gen incomplete (cover=%s, inline=%d/%d); "
                "falling back to Unsplash for missing slots.",
                bool(chatgpt_cover), len(chatgpt_inline), args.inline_count,
            )
            # Reuse what ChatGPT did produce, fill rest from Unsplash.
            inline_paths = list(chatgpt_inline)
            if chatgpt_cover:
                cover = str(chatgpt_cover.resolve())

    # Inline fallback / fill — Unsplash.
    if len(inline_paths) < args.inline_count:
        missing = args.inline_count - len(inline_paths)
        logger.info("Topping up %d inline slot(s) from Unsplash.", missing)
        unsplash_inline = _download_images(
            query, f"{slug_hint}_inline", missing,
        )
        inline_paths.extend(unsplash_inline)
    if not inline_paths and args.inline_count > 0:
        logger.error("No inline images obtained — abort")
        return 1
    if args.inline_count == 0:
        # 2026-07-28: text-first posts (essay contest entries) legitimately
        # run with zero inline images — only abort when images were asked
        # for and none arrived.
        logger.info("inline-count=0 — publishing text-only body")

    # Cover handling: explicit path > ChatGPT > Unsplash.
    override = spec.get("cover_image_path")
    if override:
        override_path = Path(override)
        if override_path.exists():
            cover = str(override_path.resolve())
            logger.info("Cover image (explicit): %s", cover)
        else:
            logger.warning(
                "cover_image_path points to missing file, falling back: %s",
                override,
            )
    if not cover:
        cover_paths = _download_images(cover_query, f"{slug_hint}_cover", 1)
        cover = str(cover_paths[0].resolve()) if cover_paths else None
        logger.info("Cover image (Unsplash fallback): %s", cover)

    # Honor a "price" field on the spec — defaults to 0 (free) to preserve
    # the legacy behaviour for posts that don't set it. Caller can also
    # override via --price.
    price = int(spec.get("price", 0))
    if args.price is not None:
        price = int(args.price)
    logger.info("Publishing at ¥%d", price)

    pub = NotePublisher(headless=False)
    try:
        url = pub.publish_article(
            title=title,
            content=content,
            tags=tags,
            price=price,
            inline_image_paths=[str(p.resolve()) for p in inline_paths],
            cover_image_path=cover,
        )
    finally:
        pub.close()

    logger.info("Published: %s", url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
