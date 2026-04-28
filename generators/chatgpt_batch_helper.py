"""Shared ChatGPT image-batch helper used by both
``scripts/publish_custom_post.py`` and ``main.py::_publish_note``.

Centralises:

* The ``USE_CHATGPT_IMAGES`` toggle.
* The Brave-running pre-check (the persistent profile is locked while
  the user has Brave open, so we must short-circuit to Unsplash to
  avoid a 90-second hang).
* Building a (cover + inline) prompt set from an article's title and
  H2 headings via :func:`generators.visual_prompt_builder.build_visual_prompt`.
* Calling :class:`ChatGPTImageGenerator.generate_batch` and returning
  ``(cover_path, [inline_paths])``.

Returning ``(None, [])`` is the failure-mode contract — callers cascade
to Unsplash or the gradient generator on that signal.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Treat anything below this as a placeholder / corrupt file so the
# caller falls through to the Unsplash cascade instead of publishing
# a broken thumbnail. ChatGPT cover PNGs are typically 1.5–3 MB.
_MIN_VALID_IMAGE_BYTES: int = 10_000


def is_chatgpt_image_gen_enabled() -> bool:
    """``USE_CHATGPT_IMAGES`` toggle.

    Default: enabled (since 2026-04-28 user request to apply Ghibli
    image generation to every platform). Set ``USE_CHATGPT_IMAGES=0``
    to disable and fall back to the Unsplash/gradient cascade.
    """
    val = os.environ.get("USE_CHATGPT_IMAGES", "1").strip().lower()
    return val not in {"", "0", "false", "no", "off"}


def is_brave_running() -> bool:
    """Detect a live ``brave.exe`` so we can skip ChatGPT (would hang).

    Excludes the BraveCrashHandler service which lingers as a system
    process and is not a real browser instance.
    """
    try:
        out = subprocess.check_output(
            ["tasklist"], text=True, errors="replace",
        )
        for ln in out.splitlines():
            stripped = ln.strip().lower()
            if stripped.startswith("brave.exe"):
                return True
    except Exception:  # noqa: BLE001 - tasklist failure ⇒ assume safe
        pass
    return False


def chatgpt_image_batch(
    title: str,
    content: str,
    inline_count: int,
    slug_hint: str,
    genre_hint: str = "general tech / lifestyle",
) -> tuple[Path | None, list[Path]]:
    """Generate (1 cover + ``inline_count`` inline) images via ChatGPT.

    H2 headings in ``content`` seed inline prompts so each image is
    bound to its section. When the article has fewer than
    ``inline_count`` H2s the slots fall back to the article title.

    Returns ``(cover_path | None, [inline_paths])``. The list of
    inline paths may be shorter than ``inline_count`` on partial
    failure — callers fill missing slots from Unsplash.
    """
    if not is_chatgpt_image_gen_enabled():
        logger.debug(
            "USE_CHATGPT_IMAGES is disabled — skipping ChatGPT batch."
        )
        return None, []

    if is_brave_running():
        logger.warning(
            "Brave is running — ChatGPT image gen requires it closed. "
            "Falling back to non-ChatGPT path."
        )
        return None, []

    try:
        from generators.chatgpt_image_generator import ChatGPTImageGenerator
        from generators.visual_prompt_builder import build_visual_prompt
    except ImportError as exc:
        logger.warning("ChatGPT image gen unavailable: %s", exc)
        return None, []

    h2s = re.findall(r"^##\s+(.+)$", content, re.MULTILINE)[:inline_count]
    while len(h2s) < inline_count:
        h2s.append(title)

    logger.info(
        "Building Ghibli prompts (%d total)…", inline_count + 1,
    )
    cover_prompt = build_visual_prompt(title, genre_hint=genre_hint)
    inline_prompts = [
        build_visual_prompt(title, section=h, genre_hint=genre_hint)
        for h in h2s
    ]
    all_prompts = [cover_prompt] + inline_prompts

    out_dir = _REPO_ROOT / "data" / "images" / "covers"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", slug_hint)[:30]
    # Unique suffix (timestamp + microseconds + PID) so two near-
    # simultaneous publish jobs cannot share a filename. Strict
    # second-resolution timestamps collided on parallel runs.
    _now = time.time()
    uniq = (
        f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(_now))}"
        f"_{int((_now % 1) * 1_000_000):06d}_{os.getpid()}"
    )
    out_paths = [out_dir / f"chatgpt_{safe}_{uniq}_cover.png"] + [
        out_dir / f"chatgpt_{safe}_{uniq}_inline_{i:02d}.png"
        for i in range(inline_count)
    ]

    logger.info(
        "Calling ChatGPT image gen (%d images, ~%d sec)…",
        len(all_prompts), len(all_prompts) * 60,
    )
    gen = ChatGPTImageGenerator(headless=False)
    results = gen.generate_batch(
        prompts=all_prompts, size="landscape", out_paths=out_paths,
    )

    def _is_valid(p: Path | None) -> bool:
        # Defence-in-depth: generate_batch already returns None for
        # failures, but a generation that wrote a 0-byte / placeholder
        # file would still hand us a Path. Verify the bytes are real
        # before treating the slot as a success — otherwise the
        # caller skips the Unsplash fallback and ships a broken cover.
        if p is None:
            return False
        try:
            return p.exists() and p.stat().st_size >= _MIN_VALID_IMAGE_BYTES
        except OSError:
            return False

    cover = results[0] if _is_valid(results[0]) else None
    inlines = [p for p in results[1:] if _is_valid(p)]
    logger.info(
        "ChatGPT batch done: cover=%s, inline=%d/%d",
        bool(cover), len(inlines), inline_count,
    )
    return cover, inlines
