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


def is_pollinations_fallback_enabled() -> bool:
    """``USE_POLLINATIONS_FALLBACK`` toggle (default OFF).

    Pollinations.ai is an HTTP-GET API, which the user has explicitly
    excluded ("API利用はNG"). The fallback is kept in code as an
    emergency escape hatch but is OFF by default — the production
    image path is ChatGPT-via-Playwright only. Set
    ``USE_POLLINATIONS_FALLBACK=1`` to opt in (e.g. for local
    debugging when ChatGPT itself is rate-limited).
    """
    val = os.environ.get("USE_POLLINATIONS_FALLBACK", "0").strip().lower()
    return val not in {"", "0", "false", "no", "off"}


def _pollinations_image_batch(
    prompts: list[str], out_paths: list[Path],
) -> list[Path | None]:
    """Generate the (cover + inline) prompt set via Pollinations.ai.

    Independent of Brave / ChatGPT — pure HTTP GET to
    ``image.pollinations.ai``. Used as a second-stage fallback inside
    :func:`chatgpt_image_batch` when ChatGPT itself failed (e.g. the
    OpenAI image-gen rate cap surfaces as a stuck send-button).
    """
    from urllib.parse import quote

    import requests as _req

    results: list[Path | None] = []
    for prompt, dest in zip(prompts, out_paths):
        try:
            url = f"https://image.pollinations.ai/prompt/{quote(prompt)}"
            params = {
                "width": 1200,
                "height": 630,
                "model": "flux",
                "nologo": "true",
                "enhance": "true",
            }
            resp = _req.get(url, params=params, timeout=120)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            size = dest.stat().st_size if dest.exists() else 0
            if size >= _MIN_VALID_IMAGE_BYTES:
                logger.info(
                    "pollinations OK: %s (%d bytes)", dest.name, size,
                )
                results.append(dest)
            else:
                logger.warning(
                    "pollinations: file too small (%d bytes) → discarding",
                    size,
                )
                results.append(None)
        except Exception as exc:  # noqa: BLE001 — fail closed per slot
            logger.warning("pollinations fail %s: %s", dest.name, exc)
            results.append(None)
    return results


def is_brave_running() -> bool:
    """Detect a live ``brave.exe`` so we can skip ChatGPT (would hang).

    Excludes the BraveCrashHandler service which lingers as a system
    process and is not a real browser instance.

    Fail-closed semantics: if `tasklist` itself errors, we cannot
    prove Brave is closed, so we report it as RUNNING. That makes
    the caller cascade to Unsplash instead of optimistically
    grabbing the locked profile (which would either hang for 90 s
    or silently pick up the user's live cookies — see Codex review
    2026-05-01 finding `chatgpt_batch_helper.py:52`).
    """
    try:
        out = subprocess.check_output(
            ["tasklist"], text=True, errors="replace",
        )
    except Exception as exc:  # noqa: BLE001 - tasklist failure ⇒ fail closed
        logger.warning(
            "is_brave_running: tasklist failed (%s) — failing closed", exc,
        )
        return True
    for ln in out.splitlines():
        stripped = ln.strip().lower()
        if stripped.startswith("brave.exe"):
            return True
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
    # Determine which engines are usable RIGHT NOW. Either path
    # produces ghibli-styled images keyed off the same prompts, so
    # the article still gets visuals matched to its content.
    chatgpt_usable = is_chatgpt_image_gen_enabled()
    pollinations_usable = is_pollinations_fallback_enabled()
    # Brave-running check is only relevant in launch_persistent_context
    # mode (we'd hit a user_data_dir lock). With CHATGPT_CDP_PORT set
    # we ATTACH to the running Brave instead, so a live Brave is the
    # required state, not a blocker. Skip the kill-switch in that case.
    cdp_attach_mode = bool(os.environ.get("CHATGPT_CDP_PORT"))
    if chatgpt_usable and not cdp_attach_mode and is_brave_running():
        logger.warning(
            "Brave is running — ChatGPT path blocked "
            "(launch mode requires Brave closed). "
            "Pollinations fallback will handle this batch."
        )
        chatgpt_usable = False
    if not chatgpt_usable and not pollinations_usable:
        logger.debug(
            "Both ChatGPT (%s) and Pollinations (%s) disabled — "
            "skipping batch.",
            chatgpt_usable, pollinations_usable,
        )
        return None, []

    try:
        from generators.visual_prompt_builder import build_visual_prompt
        if chatgpt_usable:
            from generators.chatgpt_image_generator import ChatGPTImageGenerator
    except ImportError as exc:
        logger.warning("image gen unavailable: %s", exc)
        return None, []

    # Effective inline count = min(requested, actual H2 sections).
    # Without this the previous code happily generated 4 inline images
    # for an article with only 2 H2s — note's `_inject_inline_images`
    # then dropped 2 of them on the floor (one image per H2 section)
    # which (a) burned ChatGPT daily quota and (b) left orphan PNGs
    # under data/images/covers/. Cap to actual H2 count so no image is
    # generated unless it has a section to live in.
    #
    # 2026-05-11: also extract the first ~200 chars under each H2 so
    # the image prompt can describe the section's subject concretely
    # instead of just echoing the H2 title (which is often abstract
    # like "## まとめ" / "## 前提整理").
    h2_pat = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    h2_matches = list(h2_pat.finditer(content))
    h2_sections: list[tuple[str, str]] = []  # (title, lead_body)
    for i, m in enumerate(h2_matches):
        title_text = m.group(1).strip()
        start = m.end()
        end = h2_matches[i + 1].start() if i + 1 < len(h2_matches) else len(content)
        body = content[start:end].strip()
        # Strip markdown noise (code fences, image markers, quote
        # blocks) before grabbing the lead — these are unhelpful for
        # image prompting.
        body_clean = re.sub(r"```[\s\S]*?```", "", body)
        body_clean = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body_clean)
        body_clean = re.sub(r"^>.*$", "", body_clean, flags=re.MULTILINE)
        body_clean = re.sub(r"\s+", " ", body_clean).strip()
        h2_sections.append((title_text, body_clean[:220]))
    effective_inline_count = min(inline_count, max(0, len(h2_sections)))
    if effective_inline_count < inline_count:
        logger.info(
            "[image] inline_count requested=%d → adjusted to %d "
            "(H2 sections available)",
            inline_count, effective_inline_count,
        )
    inline_count = effective_inline_count
    h2_sections = h2_sections[:inline_count]
    h2s = [t for t, _ in h2_sections]  # title-only list, kept for back-compat

    # Style pack selection. Default 'ghibli' preserves the existing
    # visual identity; setting IMAGE_STYLE_PACK=game_homage swaps in
    # one of the game-homage idioms (Smash sansen / WILD APPEARED /
    # K.O. / etc.). The chosen style is *consistent within an article*
    # — same style for cover and every inline image — so the post
    # reads as a coherent set rather than a montage.
    style_block: str | None = None
    style_label = "ghibli"
    try:
        from generators.game_homage_styles import (
            is_game_homage_enabled,
            pick_style_for_article,
        )
        if is_game_homage_enabled():
            # 2026-05-11: pass content excerpt for RAG-based style
            # selection (副業 → hunt_success, 比較 → ready_fight 等).
            # pick_style_for_article falls back to SHA-256 if RAG miss.
            chosen = pick_style_for_article(title, (content or "")[:1000])
            style_block = chosen["style_block"]
            style_label = f"game_homage:{chosen['name']}"
    except Exception as exc:  # noqa: BLE001 — never block image gen on style pick
        logger.warning("style pack selection failed (%s) — using default", exc)

    logger.info(
        "Building image prompts (%d total, style=%s)…",
        inline_count + 1, style_label,
    )
    if style_block:
        # Game-homage / explicit style: skip the Gemma3-generated
        # Japanese summary because that summary bakes in the default
        # 「水彩アニメ調」 phrasing which fights the override style.
        # Direct title-as-subject is what regen_eyecatch_smash_style.py
        # uses and it produces clean game-homage covers.
        cover_prompt = title
        inline_prompts = []
        for h_title, h_body in h2_sections:
            # 2026-05-11: pass the section body lead in addition to the
            # H2 title so abstract headings ("## まとめ" / "## 前提整理")
            # don't yield generic stock-look images. The body lead
            # gives ChatGPT a concrete subject anchor.
            subject_hint = h_body if h_body else h_title
            inline_prompts.append(
                f"記事「{title}」の「{h_title}」セクション。"
                f"このセクションは具体的に: {subject_hint[:180]}。"
                f"この内容を象徴する被写体を中央に配置。"
            )
    else:
        cover_prompt = build_visual_prompt(title, genre_hint=genre_hint)
        inline_prompts = [
            build_visual_prompt(
                title, section=h_title, genre_hint=genre_hint,
                # body_lead is a soft additional hint — visual_prompt_builder
                # tolerates an extra kwarg, falling back gracefully if unsupported.
            )
            for h_title, _ in h2_sections
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

    if chatgpt_usable:
        logger.info(
            "Calling ChatGPT image gen (%d images, ~%d sec)…",
            len(all_prompts), len(all_prompts) * 60,
        )
        try:
            gen = ChatGPTImageGenerator(headless=False)
            results = gen.generate_batch(
                prompts=all_prompts, size="landscape", out_paths=out_paths,
                topic=title, style_block=style_block,
            )
        except Exception as exc:  # noqa: BLE001 — fail open to fallback
            logger.warning(
                "ChatGPT generate_batch raised (%s) — "
                "feeding empty results to Pollinations stage", exc,
            )
            results = [None] * len(all_prompts)
    else:
        logger.info(
            "ChatGPT disabled — going straight to Pollinations for %d images",
            len(all_prompts),
        )
        results = [None] * len(all_prompts)

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

    # Pollinations fallback: when ChatGPT yielded no usable cover the
    # publish flow used to crash out to Unsplash, which is a stock
    # photo and can drift from article content. Retry the SAME prompts
    # against pollinations.ai (free, no key) so the visual still
    # matches what the article actually says.
    needs_cover_retry = cover is None
    needs_inline_retry = len(inlines) < inline_count
    if (needs_cover_retry or needs_inline_retry) and is_pollinations_fallback_enabled():
        logger.warning(
            "ChatGPT batch incomplete (cover=%s, inline=%d/%d) "
            "→ retrying via Pollinations.ai",
            bool(cover), len(inlines), inline_count,
        )
        poll_paths = [out_dir / f"poll_{safe}_{uniq}_cover.png"] + [
            out_dir / f"poll_{safe}_{uniq}_inline_{i:02d}.png"
            for i in range(inline_count)
        ]
        poll_results = _pollinations_image_batch(all_prompts, poll_paths)
        if cover is None and _is_valid(poll_results[0]):
            cover = poll_results[0]
            logger.info("pollinations supplied cover")
        # Always rebuild the inline list when fallback succeeds so we
        # don't end up with a torn (ChatGPT cover + Pollinations inline)
        # mix that visually clashes — Pollinations style is consistent
        # within its own batch.
        poll_inlines = [p for p in poll_results[1:] if _is_valid(p)]
        if not inlines and poll_inlines:
            inlines = poll_inlines
        elif len(poll_inlines) > len(inlines):
            inlines = poll_inlines
        logger.info(
            "Post-fallback: cover=%s, inline=%d/%d",
            bool(cover), len(inlines), inline_count,
        )
    return cover, inlines
