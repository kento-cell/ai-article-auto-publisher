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


_OPENING_HINTS = ("導入", "前提", "背景", "そもそも", "はじめに", "とは",
                  "なぜ", "問題", "発端", "Why")
_CONCLUDING_HINTS = ("まとめ", "結論", "総括", "おわりに", "最後に",
                     "結び", "Wrap", "次のアクション", "次のステップ",
                     "ご利用にあたって", "注意事項", "免責")
_TWIST_HINTS = ("解決", "戦略", "対策", "提案", "実践", "コツ", "突破",
                "ポイント", "How", "ハック")

# Patterns that mark a section as "main item" content — for listicle /
# comparison / multi-shop articles the per-item sections deserve image
# slots over the intro/outro frame. Matched against the H2 title.
_ITEM_PATTERNS = (
    r"^\s*\d+\s*軒目",            # 1軒目, 2軒目 (gourmet shop counter)
    r"^\s*\d+\s*店舗目",          # 1店舗目
    r"^\s*\d+\s*品目",            # 1品目
    r"^\s*\d+\s*位",              # 1位, 2位 (ranking)
    r"^\s*Top\s*\d+",             # Top 1, Top 10
    r"^\s*Case\s*\d+",            # Case 1
    r"^\s*ケース\s*\d+",           # ケース 1
    r"^\s*Pattern\s*\d+",         # Pattern 1
    r"^\s*パターン\s*\d+",         # パターン 1
    r"^\s*\d+\s*\.\s",            # 1. xxx (numbered list)
    r"^\s*第\s*\d+\s*[軒位章]",    # 第1軒, 第1位, 第1章
)


def _section_image_priority(title: str) -> int:
    """Score an H2 by how strongly it should claim an image slot.

    +100: matches an item-listing pattern (N軒目, N位, Case N …) —
          these are the per-item main content sections that benefit
          most from a section-specific image.
       0: normal main content section.
    -100: opening/intro hint (背景, はじめに, 前提 …).
    -200: concluding hint (まとめ, おわりに, ご利用にあたって …).
    """
    t = (title or "").strip()
    for pat in _ITEM_PATTERNS:
        if re.match(pat, t):
            return 100
    if any(h in t for h in _CONCLUDING_HINTS):
        return -200
    if any(h in t for h in _OPENING_HINTS):
        return -100
    return 0


def _select_image_sections(
    h2_sections: list[tuple[str, str]],
    inline_count: int,
) -> list[tuple[str, str]]:
    """Pick the top-priority H2 sections for ``inline_count`` image slots.

    Sections are scored by :func:`_section_image_priority`; ties are
    broken by article order. The returned list is re-sorted into reading
    order so inline images appear in the same flow as the article.
    """
    if not h2_sections or inline_count <= 0:
        return []
    indexed = [
        (i, t, b, _section_image_priority(t))
        for i, (t, b) in enumerate(h2_sections)
    ]
    # Priority desc, then original index asc for stable ties.
    indexed.sort(key=lambda x: (-x[3], x[0]))
    chosen = indexed[:inline_count]
    # Restore reading order.
    chosen.sort(key=lambda x: x[0])
    return [(t, b) for _, t, b, _ in chosen]


def _infer_narrative_role(idx: int, total: int, title: str) -> str:
    """Map a section to one of {起, 承, 転, 結}.

    Rules (in priority order):
    1. Last section -> 結.
    2. First section -> 起 (unless its title screams 結).
    3. Title keywords (e.g. 「まとめ」 -> 結, 「戦略」 -> 転).
    4. Fallback: 承 for the first half after 起, 転 for the second half
       before 結.
    """
    t = title or ""
    is_first = idx == 0
    is_last = idx == total - 1
    if any(h in t for h in _CONCLUDING_HINTS):
        return "結"
    if is_last:
        return "結"
    if any(h in t for h in _OPENING_HINTS):
        return "起"
    if is_first:
        return "起"
    if any(h in t for h in _TWIST_HINTS):
        return "転"
    # Midpoint heuristic
    half = total / 2
    return "承" if idx <= half else "転"


_ROLE_FEELING = {
    "起": "場面の発端、疑問の提示、これから何が起きるのか観察する状態",
    "承": "事実の展開、深掘り、内容を読者に受け取らせる落ち着いた状態",
    "転": "視点の転換、解決策の提示、行動を促す前向きな躍動感",
    "結": "結論、達成感、まとめの安堵、次のアクションを示唆する空気",
}


def _distill_subject_via_gemma(
    title: str, h_title: str, h_body: str,
    role: str, idx: int, total: int,
) -> str:
    """Ask Gemma3 to name the concrete subject for ONE section's image.

    Returns 60-char-ish Japanese subject string. Silent fallback to
    ``h_title`` on any failure so the pipeline never breaks.
    """
    if os.environ.get("IMAGE_SECTION_DISTILL", "true").lower() in (
        "false", "0", "no", "off",
    ):
        return h_title
    try:
        from generators.local_llm import LocalLLM
    except ImportError:
        return h_title
    feeling = _ROLE_FEELING.get(role, "")
    prompt = (
        "あなたは記事に挿し絵を考えるアートディレクターです。\n"
        f"記事タイトル: 「{title}」\n"
        f"このセクションは全{total}個のうち{idx + 1}番目で、\n"
        f"起承転結でいう「{role}」(={feeling})の位置にあたります。\n"
        f"セクションタイトル: 「{h_title}」\n"
        f"セクション本文 (冒頭抜粋):\n{(h_body or '')[:400]}\n\n"
        "この 1 セクションを表現する挿し絵を 1 枚描くなら、"
        "何を描けばよいか? 被写体 + 動作 + 雰囲気を 60 字以内の "
        "日本語 1 行で答えてください。前置きや解説は不要、被写体の説明文だけを返してください。"
    )
    try:
        llm = LocalLLM()
        out = llm.generate(prompt, temperature=0.6)
    except Exception as exc:  # noqa: BLE001
        logger.debug("section subject distill failed: %s", exc)
        return h_title
    # Take only the first non-empty line, trim to 80 chars to be safe.
    for line in (out or "").splitlines():
        line = line.strip().lstrip("-•*・ ").strip()
        if line and not line.startswith("#"):
            return line[:80]
    return h_title


def _build_per_section_inline_prompts(
    title: str, h2_sections: list[tuple[str, str]],
) -> list[str]:
    """Build N inline image prompts, one per H2 section, each carrying:
    (1) a Gemma3-distilled concrete subject for that section's body,
    (2) the narrative role label (起 / 承 / 転 / 結) inferred from
        section position + title keywords.

    Each prompt is what ChatGPT image gen receives — keep it short
    enough that the style_block (game_homage idiom) dominates the
    visual style, while the per-section subject controls WHO/WHAT
    appears in the frame.
    """
    total = len(h2_sections)
    prompts: list[str] = []
    for i, (h_title, h_body) in enumerate(h2_sections):
        role = _infer_narrative_role(i, total, h_title)
        feeling = _ROLE_FEELING.get(role, "")
        subject = _distill_subject_via_gemma(
            title, h_title, h_body, role, i, total,
        )
        prompts.append(
            f"記事「{title}」の「{h_title}」セクション (全{total}章中{i + 1}章、"
            f"起承転結の「{role}」役、{feeling})。"
            f"このセクションが伝えたい絵柄: {subject}。"
            f"これを象徴する被写体を中央に配置。"
        )
        logger.info(
            "[inline-prompt %d/%d role=%s] %s",
            i + 1, total, role, subject[:60],
        )
    return prompts


def _log_image_failure_incidents(
    cover_ok: bool,
    inline_got: int,
    inline_want: int,
    had_dup_md5: bool,
) -> None:
    """Surface ops_incidents relevant to a ChatGPT image-gen failure.

    2026-05-15: until now the RAG ``ops_incidents`` collection was only
    queried by the text-generation pipeline (`_log_ops_incidents_banner`
    in main.py) and the publish-time banner. The image pipeline never
    read it — so when ChatGPT image gen broke (selector drift → 23,618-
    byte note-logo placeholder → Unsplash fallback) the operator got no
    hint that this was a *known* incident already recorded in the
    registry. The user explicitly flagged this gap ("埋め込んでるのに
    読まれないの?").

    This wires the image pipeline into RAG: on a serious ChatGPT batch
    failure we query ``ops_incidents`` and emit a ``[ops-banner:image]``
    warning naming the most-similar past incidents, so a human (or
    future-Claude) reading the log immediately sees "this is the known
    selector-drift bug, the fix was X" instead of re-diagnosing.

    Not a full auto-recovery — image-gen fixes need code changes — but
    it makes the registry's knowledge actually reachable from here.
    Suppressed by ``RAG_OPS_BANNER=false`` (same switch as the text
    banner). Best-effort: silent on import / index failure.
    """
    if os.environ.get("RAG_OPS_BANNER", "true").lower() in (
        "false", "0", "no", "off",
    ):
        return
    symptom = (
        "MD5 identical placeholder image duplicated across batch"
        if had_dup_md5
        else "no image element found / size-guard rejected small placeholder"
    )
    logger.warning(
        "[ops-banner:image] ChatGPT image gen failed badly "
        "(cover=%s inline=%d/%d, symptom: %s)",
        cover_ok, inline_got, inline_want, symptom,
    )
    try:
        from generators.rag_retriever import RagRetriever
        retriever = RagRetriever()
        hits = retriever.retrieve(
            query=(
                f"passage: ChatGPT image generation failure {symptom} "
                "Brave Playwright selector placeholder Unsplash fallback"
            ),
            collection="ops_incidents",
            top_k=3,
            score_threshold=0.5,
        )
    except Exception as exc:  # noqa: BLE001 — never block image gen on RAG
        logger.debug("[ops-banner:image] retrieval failed: %s", exc)
        return
    if not hits:
        logger.warning(
            "  no matching ops_incident — if this is a NEW failure mode, "
            "add it to docs/knowledge/ops_incidents.md and re-ingest"
        )
        return
    logger.warning(
        "  %d known incident(s) — check the recorded fix before re-diagnosing:",
        len(hits),
    )
    for h in hits:
        title = h.metadata.get("section_title", "") if h.metadata else ""
        logger.warning("  - (sim %.2f) %s", h.score, title[:90])


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
    # Priority-based selection: when an article has more H2 sections
    # than image slots, prefer "main item" sections (1軒目, 2軒目, Case
    # 1 …) over background / outro frame sections. Falls back to the
    # original head-take for articles without item patterns.
    h2_sections_full = h2_sections
    h2_sections = _select_image_sections(h2_sections, inline_count)
    if [t for t, _ in h2_sections] != [t for t, _ in h2_sections_full[:inline_count]]:
        logger.info(
            "[image] section priority kicked in: %d/%d sections re-routed to per-item content",
            sum(1 for t, _ in h2_sections if _section_image_priority(t) == 100),
            inline_count,
        )
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
        # 2026-05-11 PM: per-section subject distillation via Gemma3.
        # Each H2 body (300 chars) gets distilled into a one-line
        # concrete subject (60 chars) BEFORE going to ChatGPT image gen,
        # AND tagged with a narrative role (起 / 承 / 転 / 結) inferred
        # from section position + title keywords. ChatGPT then has both
        # a concrete subject anchor AND a narrative mood hint, so each
        # inline image reads as belonging to its section rather than
        # being a topical illustration.
        inline_prompts = _build_per_section_inline_prompts(
            title=title,
            h2_sections=h2_sections,
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

    # Batch MD5 uniqueness check (Codex Critical 2026-05-14 finding).
    # When _start_new_chat() failed to reset the conversation, the URL
    # detector kept hitting the same image element across batch
    # iterations — all 11 outputs had the SAME md5 (yellow note logo).
    # File-size validation alone passed because the placeholder was
    # > _MIN_VALID_IMAGE_BYTES. Cross-check md5 of each saved file: if
    # any two files match, every collision is invalidated so we fall
    # through to Pollinations / fail rather than ship duplicates.
    import hashlib as _hashlib
    md5_to_paths: dict[str, list[Path]] = {}
    for p in results:
        if not _is_valid(p):
            continue
        try:
            h = _hashlib.md5(p.read_bytes()).hexdigest()
        except OSError:
            continue
        md5_to_paths.setdefault(h, []).append(p)
    _dup_md5s = {h for h, ps in md5_to_paths.items() if len(ps) > 1}
    if _dup_md5s:
        dup_count = sum(len(ps) for h, ps in md5_to_paths.items() if h in _dup_md5s)
        logger.warning(
            "ChatGPT batch: %d duplicate-MD5 image(s) detected across %d "
            "hash group(s) — invalidating so caller falls through to "
            "Pollinations/Unsplash instead of shipping placeholders",
            dup_count, len(_dup_md5s),
        )
        # Mark every duplicate as invalid by None-ing the slot.
        results = [
            None if (
                p is not None and _is_valid(p)
                and any(p in md5_to_paths[h] for h in _dup_md5s)
            ) else p
            for p in results
        ]

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
    # 2026-05-15: wire the image pipeline into RAG. When ChatGPT failed
    # badly (no cover, or more than half the inline slots empty) query
    # ops_incidents so the log names any known incident behind it. Only
    # fires when ChatGPT was actually attempted — a disabled-ChatGPT run
    # falling straight to Pollinations is expected, not an incident.
    if chatgpt_usable and (cover is None or len(inlines) * 2 < inline_count):
        _log_image_failure_incidents(
            cover_ok=cover is not None,
            inline_got=len(inlines),
            inline_want=inline_count,
            had_dup_md5=bool(_dup_md5s),
        )
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
