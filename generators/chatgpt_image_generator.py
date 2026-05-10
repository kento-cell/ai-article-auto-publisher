"""ChatGPT image generator via Brave + Playwright.

Drives Brave with a persistent profile (data/chatgpt-profile/) to:

1. Open https://chatgpt.com/ — relies on a previously logged-in session.
2. Start a new chat (uses ?temporary-chat=true to avoid polluting history).
3. Send a prompt that asks GPT-5.5 to generate an image of the right size.
4. Wait for the resulting <img> in the assistant turn, fetch it, save locally.

Cost = $0 (uses your ChatGPT Plus subscription). Quality = identical
to gpt-image-1.5 since ChatGPT routes the same backing model.

ToS note: Automating ChatGPT via Playwright is in OpenAI's gray zone
("automated/programmatic methods" clause). Use a dedicated account
and modest pacing.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Final, Literal, Optional

import requests
from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

logger = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# Working profile used by Playwright. We copy the user's real Brave
# profile (Cookies, Local Storage etc.) into here so the running Brave
# instance keeps its lock on the original directory and our automation
# still inherits the ChatGPT login state. Cheaper than full sync — we
# only mirror the auth-relevant files.
_PROFILE_DIR: Final[Path] = _REPO_ROOT / "data" / "chatgpt-profile"

# Source: real Brave default profile. Override via env var if needed.
import os
_BRAVE_USER_DATA: Final[Path] = Path(
    os.environ.get(
        "BRAVE_USER_DATA",
        r"C:\Users\user\AppData\Local\BraveSoftware\Brave-Browser\User Data",
    )
)
_BRAVE_PATH: Final[str] = (
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
)

# `_AUTH_FILES` / `_AUTH_DIRS` removed 2026-05-01 — they enumerated
# the cookie / session-storage / login DB files that the now-deleted
# `_sync_auth_from_brave` copied between profiles. Keeping the names
# would have invited future code to re-read those secrets.

# Default landing URL. Resolution order:
#   1. ``data/chatgpt-image-chat-url.txt`` (auto-persisted last
#      personal /c/<id> URL after a share-URL upgrade)
#   2. ``CHATGPT_IMAGE_CHAT_URL`` env var
#   3. https://chatgpt.com/   (lands on the most-recent chat)
#
# The point: pin ALL image generations to ONE conversation across
# pipeline runs to avoid sidebar pollution and the "new chat per
# batch" perf hit.

_CHAT_URL_CACHE_FILE: Final[Path] = (
    Path(__file__).resolve().parent.parent
    / "data" / "chatgpt-image-chat-url.txt"
)


_DEFAULT_CHATGPT_URL: Final[str] = "https://chatgpt.com/"
# Note: ?temporary-chat=true was tried 2026-05-07 to bypass Memory
# but ChatGPT disables the image-generation tool inside temporary
# chats ("このチャットでは画像生成ツールにアクセスできません").
# Reverted to the regular new-chat URL; Memory pollution is fought
# instead by the anti-template directive in `_build_prompt`.


def _is_safe_chatgpt_url(url: str) -> bool:
    """Defence-in-depth: an attacker who can write
    `data/chatgpt-image-chat-url.txt` (or set the env var) could
    otherwise redirect Playwright — running with the user's Brave
    cookies — to a phishing host that harvests session tokens or
    runs hostile JS in `_send_prompt`. Restrict to the
    chatgpt.com / chat.openai.com origins we actually use."""
    return (
        url.startswith("https://chatgpt.com/")
        or url.startswith("https://chat.openai.com/")
    )


def _resolve_chat_url() -> str:
    if _CHAT_URL_CACHE_FILE.exists():
        cached = _CHAT_URL_CACHE_FILE.read_text(encoding="utf-8").strip()
        if cached and _is_safe_chatgpt_url(cached):
            return cached
        if cached:
            logger.warning(
                "ignoring suspicious cached chat URL %r — falling back",
                cached[:80],
            )
    env = os.environ.get("CHATGPT_IMAGE_CHAT_URL")
    if env and _is_safe_chatgpt_url(env):
        return env
    if env:
        logger.warning(
            "ignoring CHATGPT_IMAGE_CHAT_URL env (not a chatgpt.com URL)",
        )
    return _DEFAULT_CHATGPT_URL


_CHATGPT_NEW_CHAT: Final[str] = _resolve_chat_url()

_NAV_TIMEOUT: Final[int] = 60_000
# Image generation takes 30-90s typically. Cap at 4min to recover.
_IMAGE_WAIT_TIMEOUT: Final[int] = 240_000

# Text-reply waiting (used by Vision evaluation). ChatGPT typically
# answers a 2-line scoring prompt in 5-15s; cap at 60s.
_TEXT_WAIT_TIMEOUT: Final[int] = 120_000

# Vision-evaluation thresholds. The evaluator asks ChatGPT to score the
# just-generated image 1-10 against the article topic. Below cutoff →
# regenerate once. Default cutoff is forgiving (6/10) so the retry
# fires only on clear topic-drift, not stylistic preferences.
_VISION_EVAL_CUTOFF: Final[int] = 6
# Max retries per image. Hard-coded to 1 to bound latency: a flaky
# generation can already happen, doubling that without limit would
# triple per-batch wall time on bad days.
_VISION_EVAL_MAX_RETRIES: Final[int] = 1


def _vision_eval_enabled() -> bool:
    """``CHATGPT_VISION_EVAL`` toggle. Default ON since 2026-05-01:
    the K-beauty-image-on-Claude-Code-article incident showed that
    silent fallbacks (stale chat-cache, mis-keyed stock photos) can
    ship topical-mismatched covers without any error. Vision eval is
    cheap (one extra ChatGPT turn) and catches the divergence before
    upload. Set ``CHATGPT_VISION_EVAL=0`` to opt out for debugging."""
    val = os.environ.get("CHATGPT_VISION_EVAL", "1").strip().lower()
    return val not in {"0", "false", "no", "off"}

Size = Literal["landscape", "portrait", "square"]
_SIZE_PHRASE: Final[dict[Size, str]] = {
    "landscape": "16:9 横長 (1792×1024 ピクセル)",
    "portrait":  "9:16 縦長 (1024×1792 ピクセル)",
    "square":    "1:1 正方形 (1024×1024 ピクセル)",
}


class ChatGPTImageGenerator:
    """Generate cover images by automating ChatGPT (Brave browser)."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._profile_dir = _PROFILE_DIR
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        # CDP attach state — when set, _close_browser() leaves the
        # underlying Brave alive and only tears down the tab we created.
        self._cdp_browser = None
        self._cdp_attached = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_batch(
        self,
        prompts: list[str],
        size: Size = "landscape",
        out_paths: Optional[list[Path]] = None,
        topic: str = "",
        style_block: str | None = None,
    ) -> list[Optional[Path]]:
        """Generate multiple images in a single ChatGPT session.

        Reuses the same browser+chat across prompts — 3-5× faster than
        calling :meth:`generate` repeatedly because we skip
        N-1 launch+navigate+new-chat cycles. Also produces only one
        sidebar entry per article instead of N.

        Args:
            prompts: List of visual descriptions, one per image.
            size: Aspect ratio applied to every image.
            out_paths: Optional list of save paths. Must match the
                length of ``prompts`` if supplied. Auto-generated
                otherwise.

        Returns:
            List of saved paths (or ``None`` per slot for any failure).
        """
        if not prompts:
            return []
        if out_paths is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_dir = _REPO_ROOT / "data" / "images" / "covers"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_paths = [
                out_dir / f"chatgpt_batch_{ts}_{i:02d}.png"
                for i in range(len(prompts))
            ]
        if len(out_paths) != len(prompts):
            raise ValueError("out_paths length must match prompts length")

        results: list[Optional[Path]] = [None] * len(prompts)
        eval_on = _vision_eval_enabled()
        try:
            self._open_browser()
            for i, (prompt, dest) in enumerate(zip(prompts, out_paths)):
                logger.info(
                    "batch image %d/%d (fresh chat per image)",
                    i + 1, len(prompts),
                )
                # Per-image session policy (2026-05-07 user request):
                # 1) Open a NEW chat for every image so this generation
                #    cannot inherit pollution from the previous prompt's
                #    context (different topic, retry feedback, vision
                #    eval text).
                # 2) Delete the chat immediately after extracting the
                #    image so the sidebar stays clean and the user's
                #    history doesn't accumulate one entry per published
                #    article.
                # `seen_urls` is reset inside this loop because each
                # chat is brand-new and previous URLs cannot collide.
                seen_urls: set[str] = set()
                try:
                    self._start_new_chat()
                except (PlaywrightTimeoutError, PlaywrightError) as exc:
                    logger.warning(
                        "batch %d: new chat open failed: %s — "
                        "continuing on existing tab",
                        i + 1, exc,
                    )

                # Convention from publish_custom_post.py: prompts[0] is
                # the article cover, rest are inline section visuals.
                is_cover = (i == 0)
                full_prompt = self._build_prompt(
                    prompt, size, is_cover=is_cover,
                    style_block=style_block,
                )
                try:
                    self._send_prompt(full_prompt)
                    img_url = self._wait_for_image(skip_urls=seen_urls)
                    if not img_url:
                        logger.error("batch %d: no image found", i + 1)
                    else:
                        seen_urls.add(img_url)
                        self._download_via_browser(img_url, dest)
                        results[i] = dest

                        if eval_on and topic:
                            kind = "サムネ" if is_cover else "インライン"
                            if not self._image_passes_vision_eval(
                                topic=topic, kind=kind,
                            ):
                                logger.warning(
                                    "batch %d vision-eval failed; "
                                    "regenerating once", i + 1,
                                )
                                retry_prompt = self._build_retry_prompt(
                                    prompt, size, is_cover, topic,
                                )
                                try:
                                    self._send_prompt(retry_prompt)
                                    new_url = self._wait_for_image(
                                        skip_urls=seen_urls,
                                    )
                                    if new_url:
                                        seen_urls.add(new_url)
                                        self._download_via_browser(
                                            new_url, dest,
                                        )
                                        results[i] = dest
                                except (
                                    PlaywrightTimeoutError, PlaywrightError,
                                ) as exc:
                                    logger.warning(
                                        "batch %d retry failed: %s — "
                                        "keeping original", i + 1, exc,
                                    )
                except (PlaywrightTimeoutError, PlaywrightError) as exc:
                    logger.error("batch %d failed: %s", i + 1, exc)
                finally:
                    # Always delete this chat — even on send-prompt
                    # timeout we still left a /c/<id> conversation that
                    # would pollute the sidebar.
                    try:
                        self._delete_current_chat()
                    except PlaywrightError as exc:
                        logger.warning(
                            "batch %d delete chat failed: %s", i + 1, exc,
                        )
        finally:
            self._close_browser()
        return results

    # ------------------------------------------------------------------
    # Vision evaluation (opt-in via CHATGPT_VISION_EVAL=1)
    # ------------------------------------------------------------------

    def _image_passes_vision_eval(self, topic: str, kind: str) -> bool:
        """Ask ChatGPT to score the most-recent image vs the article topic.

        Sends a short scoring prompt, waits for the text reply, parses
        the SCORE: <n> line, and returns True iff n >= cutoff.

        Fail-closed semantics (changed 2026-05-01 per Codex review):
        any infrastructure failure (no reply, unparseable score, browser
        error) is treated as FAIL so the caller regenerates instead of
        shipping an unverified image. Previously these all pass-through
        which silently masked vision-eval being effectively off.
        """
        try:
            eval_prompt = (
                "いま生成した画像について評価してください。\n"
                f"記事テーマ: 『{topic[:120]}』\n"
                f"用途: {kind}画像\n\n"
                "以下のフォーマットで1行ずつ返答:\n"
                "SCORE: <1-10の整数。記事内容との合致度+水彩アニメ調の品質>\n"
                "REASON: <1行、なぜその点数か>\n\n"
                "余計な前置き・後置きは不要。"
            )
            self._send_prompt(eval_prompt)
            reply = self._wait_for_text_reply()
            if not reply:
                logger.warning(
                    "vision-eval: no reply parseable; FAIL (fail-closed)",
                )
                return False
            score = self._parse_vision_score(reply)
            if score is None:
                logger.warning(
                    "vision-eval: SCORE not parseable from %r — FAIL "
                    "(fail-closed)",
                    reply[:120],
                )
                return False
            ok = score >= _VISION_EVAL_CUTOFF
            logger.info(
                "vision-eval: score=%d cutoff=%d → %s",
                score, _VISION_EVAL_CUTOFF, "PASS" if ok else "FAIL",
            )
            return ok
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            logger.warning(
                "vision-eval browser error: %s — FAIL (fail-closed)", exc,
            )
            return False

    def _wait_for_text_reply(self) -> Optional[str]:
        """Wait for ChatGPT's latest assistant turn to finish streaming.

        Polls innerText of the last ``[data-message-author-role='assistant']``
        element. Considers the turn done when the text has stabilized AND
        the streaming-progress indicator (思考中 / Thinking / cursor blob)
        has cleared.

        2026-05-08 fix: previously the 2-sec stability check returned
        "思考中" prematurely (the placeholder is itself stable while the
        model is still thinking) — vision-eval then failed to parse a
        non-existent SCORE and the entire batch fell back to Unsplash.
        """
        if self._page is None:
            return None
        deadline = time.time() + _TEXT_WAIT_TIMEOUT / 1000
        select_js = """() => {
            const turns = document.querySelectorAll(
                '[data-message-author-role="assistant"]'
            );
            if (!turns.length) return null;
            return (turns[turns.length - 1].innerText || '').trim();
        }"""
        # Indicators ChatGPT shows WHILE still generating. Returning these
        # as the final answer = bug (they're transient). Stay in the loop
        # until they go away.
        thinking_markers = (
            "思考中", "考え中", "回答を生成", "生成中",
            "Thinking", "thinking", "Reasoning", "reasoning",
        )

        def _is_placeholder(t: str) -> bool:
            stripped = t.strip()
            if not stripped:
                return True
            # Treat as placeholder when the entire reply is essentially
            # one of the markers (allowing for surrounding whitespace /
            # punctuation but not for substantive content alongside).
            if len(stripped) <= 24 and any(m in stripped for m in thinking_markers):
                return True
            # Last-line check: if the reply ends with a thinking marker
            # the model is still producing — keep waiting.
            tail = stripped.splitlines()[-1].strip() if stripped else ""
            if tail and len(tail) <= 12 and any(m in tail for m in thinking_markers):
                return True
            return False

        last_text = ""
        stable_for = 0
        while time.time() < deadline:
            try:
                cur = self._page.evaluate(select_js) or ""
            except PlaywrightError:
                cur = ""
            if cur and cur == last_text:
                stable_for += 1
                # Need: stable for 2 polls AND not a placeholder.
                if stable_for >= 2 and not _is_placeholder(cur):
                    return cur
            else:
                stable_for = 0
                last_text = cur
            self._page.wait_for_timeout(1_000)
        # On timeout, return whatever we have IF it's not a placeholder.
        # A placeholder reply means ChatGPT didn't finish — caller will
        # treat None as fail-closed.
        if last_text and not _is_placeholder(last_text):
            return last_text
        return None

    @staticmethod
    def _parse_vision_score(reply: str) -> Optional[int]:
        """Extract the SCORE: <n> integer. Tolerant of stray prose."""
        m = re.search(r"SCORE\s*[:：]\s*(\d{1,2})", reply, re.IGNORECASE)
        if not m:
            # Fallback: grab the first standalone digit 1-10 in the reply.
            m = re.search(r"\b([1-9]|10)\s*\s*[/／]?\s*10\b", reply)
        if not m:
            return None
        try:
            n = int(m.group(1))
        except ValueError:
            return None
        return max(1, min(10, n))

    @staticmethod
    def _build_retry_prompt(
        prompt: str, size: Size, is_cover: bool, topic: str,
    ) -> str:
        kind = "サムネイル画像" if is_cover else "インライン画像"
        return (
            f"前回の{kind}は記事内容『{topic[:80]}』とズレていました。\n"
            "もう一度、以下の方針で生成し直してください。\n\n"
            f"【記事の内容】\n{prompt}\n\n"
            f"【サイズ】\n{_SIZE_PHRASE[size]}\n\n"
            "【スタイル】\n"
            "宮崎駿、新海誠、細田守のような日本のアニメ監督の作風を参考に、\n"
            "手描き水彩アニメーション調で、記事のテーマと直接関係する被写体を中心に。\n"
            "前回のような抽象的・無関係な描写は避けてください。\n\n"
            "出力は画像のみ。"
        )

    def _start_new_chat(self) -> None:
        """Open a brand-new tab + chat for the next image.

        Per-image tab policy (2026-05-07 user request):
          * CDP attach mode — close the previous tab and open a fresh
            ``ctx.new_page()``, then navigate to chatgpt.com. This
            guarantees a clean composer with no leftover scroll /
            modal / sidebar state from the previous image.
          * Launch mode — keep the single tab and just ``goto()`` the
            new-chat URL (creating a tab here would conflict with the
            launch context's lifecycle).

        Either way, ``self._page`` ends up pointing at the active
        composer ready for ``_send_prompt``.
        """
        if self._context is None:
            return
        if self._cdp_attached:
            # Close the previous tab first so the sidebar isn't
            # littered with stale chatgpt.com tabs across batches.
            if self._page is not None:
                try:
                    self._page.close()
                except PlaywrightError:
                    pass
                self._page = None
            try:
                self._page = self._context.new_page()
                self._page.set_default_timeout(_NAV_TIMEOUT)
            except PlaywrightError as exc:
                logger.warning(
                    "_start_new_chat: new_page failed: %s", exc,
                )
                return
        if self._page is None:
            return
        try:
            self._page.goto(
                _DEFAULT_CHATGPT_URL, wait_until="domcontentloaded",
            )
            # Composer needs a beat to mount its prompt-textarea.
            self._page.wait_for_timeout(1_500)
            self._dismiss_blocking_dialogs()
        except PlaywrightTimeoutError as exc:
            logger.warning(
                "_start_new_chat: nav timeout (%s) — staying on current tab",
                exc,
            )

    def _cleanup_orphan_tabs(self) -> None:
        """Close stray about:blank / new-tab pages we may have left.

        ``new_page()`` and chromium's session-restore can leave behind
        empty tabs (about:blank, chrome://newtab/) that pollute the
        user's tab strip. This walks every page in the context and
        closes the empty ones, leaving real user pages alone.
        Safe to call repeatedly.
        """
        if self._context is None:
            return
        empty = {"", "about:blank", "chrome://newtab/"}
        for pg in list(self._context.pages):
            try:
                if pg is self._page:
                    continue  # never close our own working tab
                url = pg.url or ""
                if url in empty or url.startswith("about:"):
                    pg.close()
                    logger.info("closed orphan tab: %s", url[:80])
            except PlaywrightError:
                continue

    def _dismiss_blocking_dialogs(self) -> None:
        """Close any modal dialog covering the composer.

        ``temporary-chat=true`` and other onboarding flows render a
        ``<dialog open>`` that intercepts pointer events so the
        composer ``.click()`` retries forever. Press Escape (works for
        most ChatGPT modals), then explicitly click any visible
        dismiss button as a backup.
        """
        if self._page is None:
            return
        try:
            self._page.keyboard.press("Escape")
            self._page.wait_for_timeout(300)
        except PlaywrightError:
            pass
        for sel in (
            "dialog button[aria-label='閉じる']",
            "dialog button[aria-label='Close']",
            "dialog button:has-text('始める')",
            "dialog button:has-text('OK')",
            "dialog button:has-text('続ける')",
            "dialog button:has-text('Continue')",
            "dialog button:has-text('Got it')",
        ):
            try:
                btn = self._page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2_000)
                    self._page.wait_for_timeout(300)
                    logger.info(
                        "dismissed dialog via selector %s", sel,
                    )
                    return
            except PlaywrightError:
                continue

    def _delete_current_chat(self) -> None:
        """Soft-delete the conversation we just used.

        ChatGPT's "delete" in the sidebar issues a PATCH to
        ``/backend-api/conversation/<id>`` with ``is_visible: false``.
        We mirror that via ``fetch`` from the page context so cookies
        and CSRF tokens flow naturally. If the page isn't on a
        personal ``/c/<id>`` URL (e.g. we never left a share view)
        there's nothing to clean up.
        """
        if self._page is None:
            return
        url = self._page.url or ""
        m = re.search(r"/c/([0-9a-fA-F-]{8,})", url)
        if not m:
            logger.debug(
                "_delete_current_chat: not on /c/<id> URL (%s); skip",
                url[:80],
            )
            return
        chat_id = m.group(1)
        try:
            # ChatGPT's PATCH conversation endpoint requires a
            # Bearer token (cookies alone return 401). Grab it via
            # /api/auth/session, then send the PATCH with
            # Authorization: Bearer <token> attached.
            result = self._page.evaluate(
                """async (chatId) => {
                    let token = null;
                    try {
                        const sess = await fetch('/api/auth/session', {
                            credentials: 'include',
                        });
                        if (sess.ok) {
                            const j = await sess.json();
                            token = j.accessToken || null;
                        }
                    } catch (e) {}
                    const headers = {'Content-Type': 'application/json'};
                    if (token) headers['Authorization'] = 'Bearer ' + token;
                    const r = await fetch(
                        '/backend-api/conversation/' + chatId,
                        {
                            method: 'PATCH',
                            headers,
                            body: JSON.stringify({is_visible: false}),
                            credentials: 'include',
                        }
                    );
                    return {status: r.status, ok: r.ok, hadToken: !!token};
                }""",
                chat_id,
            )
            if result and result.get("ok"):
                logger.info(
                    "soft-deleted chat %s from ChatGPT sidebar",
                    chat_id[:12],
                )
            else:
                logger.warning(
                    "delete chat %s returned %s",
                    chat_id[:12], result,
                )
        except PlaywrightError as exc:
            logger.warning("delete chat fetch raised: %s", exc)

    @staticmethod
    def _build_prompt(
        prompt: str,
        size: Size,
        is_cover: bool = False,
        style_block: str | None = None,
    ) -> str:
        """Compose the imperative prompt sent to ChatGPT (Japanese).

        Format requested by the user (2026-04-28):
          1. 「この記事のサムネ/インライン画像を作成してください」
          2. 記事の要約 (prompt argument is the JP summary of the
             article, produced by visual_prompt_builder)
          3. サイズ指定
          4. スタイルブロック (default: 宮崎駿/新海誠/細田守風)
             — caller can override with ``style_block`` (game-homage,
             cyberpunk, etc.). Keeping default Ghibli preserves
             backwards-compat for every existing caller.
          5. 全部日本語

        ``is_cover`` switches the noun between サムネイル / インライン.
        """
        kind = "サムネイル画像" if is_cover else "インライン画像"
        # Default Ghibli-ish block. 2026-04-28: 「スタジオジブリ風」直書き
        # が OpenAI の第三者コンテンツモデレーションに引っかかるようになっ
        # たので、商標名を外して個人クリエイター名 + テクニカルな描写語に
        # 分散。日本のアニメ監督 (宮崎駿/新海誠/細田守) の名前なら個人芸
        # 術家として通る。
        default_style = (
            "宮崎駿、新海誠、細田守のような日本のアニメ監督の作風を参考に、\n"
            "温かみのある手描き水彩アニメーション調で生成してください。\n"
            "- 手描き水彩タッチ、優しいパステルカラー、温かい光\n"
            "- 夢幻的・ノスタルジックな雰囲気、自然光\n"
            "- キャラクターや自然背景・建物が登場してOK\n"
            "- テキスト・読める文字・ロゴ・透かし・UIスクリーンショットは描かない\n"
            "- 中央に被写体を配置、シネマティックな構図"
        )
        style = style_block.strip() if style_block else default_style
        # Anti-template-prompt directive (2026-05-07):
        # ChatGPT Memory has been observed to repeatedly answer image
        # requests with a fixed 5-item template ("【記事の内容】
        # 【サイズ】【スタイル】【入れたい要素】【文字入れ】を送って
        # ください") instead of generating. Force-override that
        # behaviour: lead with an explicit "no clarifying questions"
        # statement, give every field inline, and end with a final
        # imperative the model has to honour for compliance.
        if is_cover:
            # 煽動的・文字入りサムネ専用プロンプト (2026-05-07 user request)
            # Inline images stay Ghibli / clean illustration; ONLY the
            # cover gets the click-bait infographic treatment with
            # large hand-drawn Japanese title text + character + bold
            # background. Goal: thumbnail is the click-driver, body
            # images are the calm complement.
            return (
                f"【最重要】このメッセージで全情報を提供しています。"
                f"絶対に追加質問せず、即座に画像を1枚生成してください。\n"
                f"テンプレート確認・項目の聞き返し・「もう少し情報を」"
                f"などの応答は禁止です。\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"用途: note記事のアイキャッチ・サムネ画像 (1枚)\n"
                f"サイズ: {_SIZE_PHRASE[size]}\n"
                f"目的: クリック率を最大化する煽動的・文字入りバナー\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"【★最重要★ 文字を必ず画像内に大きく描画】\n"
                f"メインキャッチ文字 (画像中央〜上部に巨大日本語ゴシックで):\n"
                f"  「{prompt[:60]}」\n"
                f"  ※この文字の主要キーワード3〜5語を抜き出し、\n"
                f"    一番大きく目立つように描いてください\n"
                f"  ※フォント: 極太ゴシック / 漫画風手書き風\n"
                f"  ※色: 黒地+白文字 / 赤地+黄文字 / 白地+黒文字 など強コントラスト\n"
                f"  ※縁取り (3-5px 反対色) + ドロップシャドウ必須\n"
                f"  ※文字はくっきり読めること。絶対にぼかさない\n\n"
                f"【キャラ・象徴イラスト】\n"
                f"記事の被写体: {prompt}\n"
                f"  ※左右どちらかにアニメ風キャラ or 象徴イラストを大きく配置\n"
                f"  ※表情豊か (驚き / ニヤリ / 真剣 など)、視線を文字に誘導\n"
                f"  ※文字と被らない位置にレイアウト\n\n"
                f"【背景】\n"
                f"  - ビビッドな単色 or 2色グラデ (赤・紫・青・黄・ピンク系から選択)\n"
                f"  - 装飾を1-2個入れる: 集中線 / きらめき / 吹き出し / 矢印 / 雷光\n"
                f"  - 全体構図は YouTube サムネ・雑誌の煽り広告型\n\n"
                f"【スタイル】\n"
                f"  - インフォグラフィック型 / バナー型\n"
                f"  - SNS (note・Twitter・YouTube) でクリックされやすい煽動レイアウト\n"
                f"  - アニメ風キャラOK、ポップ・カラフル\n"
                f"  - 既存IPの商標ロゴ・実在キャラの直接描写は避ける\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"出力は画像1枚のみ。前置き・後置きの文章不要。"
                f"質問・確認・テンプレ要求は一切禁止。"
                f"必ず日本語の文字を画像内にはっきり描いてください。"
            )
        # インライン画像: 従来通り Ghibli / クリーン水彩。本文を邪魔しない補完絵。
        return (
            f"【最重要】このメッセージで全情報を提供しています。"
            f"絶対に追加質問せず、即座に画像を1枚生成してください。\n"
            f"テンプレート確認・項目の聞き返し・「もう少し情報を」"
            f"などの応答は禁止です。\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"用途: 記事のインライン画像 (本文中の挿絵、1枚)\n"
            f"サイズ: {_SIZE_PHRASE[size]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"記事の被写体・場面（これをそのまま描いてください）:\n"
            f"{prompt}\n\n"
            f"スタイル指定:\n"
            f"{style}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"出力は画像1枚のみ。前置き・後置きのテキスト不要。"
            f"質問・確認・テンプレ要求は一切禁止。"
        )

    def generate(
        self,
        prompt: str,
        size: Size = "landscape",
        out_path: Optional[Path] = None,
        style_block: str | None = None,
    ) -> Optional[Path]:
        """Generate one image and save to *out_path*.

        Args:
            prompt: Visual description in natural language. Avoid
                style fluff; describe subject, mood, palette, framing.
            size: ``landscape`` (best for note/Zenn covers),
                ``portrait``, or ``square``.
            out_path: Where to save. Defaults to data/images/covers/
                with a timestamped filename.

        Returns:
            Local path of saved image, or ``None`` if generation failed.
        """
        if out_path is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_dir = _REPO_ROOT / "data" / "images" / "covers"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"chatgpt_cover_{ts}.png"

        full_prompt = self._build_prompt(prompt, size, style_block=style_block)

        try:
            self._open_browser()
            # Snapshot every image URL already on the page (the fixed
            # share-URL chat carries history from prior runs). Without
            # this, _wait_for_image picks the largest existing image —
            # often a previous topic's result — instead of waiting for
            # the freshly-generated one.
            preexisting: set[str] = set()
            try:
                preexisting = set(self._page.evaluate(
                    """() => Array.from(document.querySelectorAll('img'))
                        .map(i => i.src)
                        .filter(s => s && (s.startsWith('https://') || s.startsWith('blob:')))"""
                ) or [])
            except Exception as exc:
                logger.warning("preexisting-image snapshot failed: %s", exc)
            self._send_prompt(full_prompt)
            img_url = self._wait_for_image(skip_urls=preexisting)
            if not img_url:
                logger.error("ChatGPT image generation: no image element found")
                return None
            # ChatGPT-served images require the same cookies used to load
            # the page (the URL is /backend-api/estuary/content with a
            # signed query plus session auth). Download via Playwright
            # so the request inherits the browser context.
            self._download_via_browser(img_url, out_path)

            # Vision-eval gate (default ON since 2026-05-01). The topic
            # passed to the evaluator is the original Japanese visual
            # summary — not the wrapper template — so the LLM scores
            # the actual subject match. On low-score, retry once with
            # a "前回はズレていた" feedback prompt.
            if _vision_eval_enabled() and prompt:
                kind = "サムネ"
                if not self._image_passes_vision_eval(topic=prompt, kind=kind):
                    logger.warning(
                        "single-gen vision-eval failed; regenerating once",
                    )
                    seen = preexisting | {img_url}
                    retry_prompt = self._build_retry_prompt(
                        prompt, size, is_cover=True, topic=prompt,
                    )
                    try:
                        self._send_prompt(retry_prompt)
                        new_url = self._wait_for_image(skip_urls=seen)
                        if new_url:
                            self._download_via_browser(new_url, out_path)
                    except (PlaywrightTimeoutError, PlaywrightError) as exc:
                        logger.warning(
                            "single-gen retry failed: %s — keeping original",
                            exc,
                        )
            return out_path
        except PlaywrightTimeoutError as exc:
            logger.error("ChatGPT image gen timeout: %s", exc)
            return None
        except PlaywrightError as exc:
            logger.error("ChatGPT image gen browser error: %s", exc)
            return None
        finally:
            self._close_browser()

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    def _open_browser(self) -> None:
        """Open the working ChatGPT page.

        Two strategies, in priority order:

        1. **CDP attach** (preferred) — if ``CHATGPT_CDP_PORT`` is set
           we connect to a Brave that's already running with
           ``--remote-debugging-port=<port>`` and open a NEW tab on
           ``chatgpt.com``. The user's existing tabs are never
           inspected or closed, and Brave stays alive across runs so
           the next ``--publish`` doesn't re-pay the launch cost.
        2. **launch_persistent_context** (fallback) — kicks off our
           own Brave instance against the user's real profile. This
           requires Brave to be closed (otherwise the user_data_dir
           is locked) and is what the pipeline used before 2026-05-07.
        """
        cdp_port = os.environ.get("CHATGPT_CDP_PORT")
        if cdp_port:
            cdp_url = f"http://localhost:{cdp_port}"
            try:
                self._playwright = sync_playwright().start()
                self._cdp_browser = (
                    self._playwright.chromium.connect_over_cdp(cdp_url)
                )
                if not self._cdp_browser.contexts:
                    raise PlaywrightError(
                        "CDP browser exposed no contexts",
                    )
                self._context = self._cdp_browser.contexts[0]
                self._cdp_attached = True
                logger.info(
                    "CDP attached to Brave at %s "
                    "(%d existing tabs preserved)",
                    cdp_url, len(self._context.pages),
                )
                # Sweep any pre-existing about:blank / chrome://newtab
                # tabs left behind by chromium session-restore so we
                # don't leak them into the user's tab strip.
                self._cleanup_orphan_tabs()
                self._page = self._context.new_page()
                self._page.set_default_timeout(_NAV_TIMEOUT)
                # NOTE: skipping _install_navigation_guard in CDP mode
                # — context.route is shared across the user's existing
                # tabs and would block their non-chatgpt navigation.
                # We rely on never goto-ing anywhere but chatgpt.com/.
                self._page.goto(
                    _DEFAULT_CHATGPT_URL,
                    wait_until="domcontentloaded",
                )
                self._page.wait_for_timeout(2_500)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "CDP connect to %s failed (%s) — "
                    "falling back to launch_persistent_context",
                    cdp_url, exc,
                )
                if self._playwright is not None:
                    try:
                        self._playwright.stop()
                    except PlaywrightError:
                        pass
                self._playwright = None
                self._cdp_browser = None
                self._cdp_attached = False

        target_profile = (
            _BRAVE_USER_DATA if _BRAVE_USER_DATA.exists()
            else self._profile_dir
        )
        logger.info("Brave user_data_dir: %s", target_profile)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(target_profile),
            executable_path=_BRAVE_PATH,
            headless=self._headless,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = (
            self._context.pages[0] if self._context.pages
            else self._context.new_page()
        )
        self._page.set_default_timeout(_NAV_TIMEOUT)
        # Defence-in-depth: when Playwright runs against the user's
        # personal Brave profile, every cookie & sessionStorage entry
        # for every site they're logged into is in scope. A bug or
        # hostile chat-URL that redirected the top frame to evil.com
        # would hand that origin first-party access to whatever
        # cookies their domain carries (and a chance to phish via a
        # _send_prompt() call). The route hook below aborts any
        # top-frame document load that isn't on a chatgpt.com /
        # chat.openai.com host. Sub-resources (CSS/fonts/CDN) are
        # untouched so the legitimate ChatGPT page still works.
        self._install_navigation_guard()
        self._page.goto(_CHATGPT_NEW_CHAT, wait_until="domcontentloaded")
        self._page.wait_for_timeout(2_500)

        # If we landed on a share URL the page may be read-only. Try
        # to:
        # (a) follow a "Continue this conversation" CTA (usually
        #     present for non-owners), or
        # (b) detect that the page redirected to /c/<id> automatically
        #     (happens when the share owner visits their own share),
        #     and otherwise
        # (c) fall back to https://chatgpt.com/ which lands on the
        #     most-recently-opened personal chat.
        if "/share/" in (self._page.url or ""):
            for sel in (
                "button:has-text('Continue this conversation')",
                "button:has-text('この会話を続ける')",
                "a:has-text('Continue this conversation')",
                "a:has-text('この会話を続ける')",
            ):
                btn = self._page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    try:
                        btn.click()
                        self._page.wait_for_load_state(
                            "domcontentloaded", timeout=15_000,
                        )
                        self._page.wait_for_timeout(1_500)
                        new_url = self._page.url
                        logger.info("share-URL continued → %s", new_url)
                        # Persist the resolved /c/<id> URL so future
                        # runs skip the share-redirect dance. Only
                        # cache origins we trust — see
                        # _is_safe_chatgpt_url for rationale.
                        if "/c/" in new_url and _is_safe_chatgpt_url(new_url):
                            try:
                                _CHAT_URL_CACHE_FILE.parent.mkdir(
                                    parents=True, exist_ok=True,
                                )
                                _CHAT_URL_CACHE_FILE.write_text(
                                    new_url, encoding="utf-8",
                                )
                                logger.info(
                                    "cached chat URL for next run: %s",
                                    _CHAT_URL_CACHE_FILE,
                                )
                            except OSError as exc:
                                logger.warning(
                                    "couldn't cache chat URL: %s", exc,
                                )
                        break
                    except PlaywrightError:
                        continue
        # Final safety net: if we are still stuck on /share/ AND no
        # composer is reachable, fall back to chatgpt.com/ which lands
        # on the last personal chat. Otherwise the test would burn 4
        # minutes timing out waiting for an image we can't request.
        if "/share/" in (self._page.url or ""):
            composer_visible = False
            try:
                comp = self._page.locator(
                    "#prompt-textarea, div[contenteditable='true']"
                ).first
                composer_visible = (
                    comp.count() > 0 and comp.is_visible()
                )
            except PlaywrightError:
                pass
            if not composer_visible:
                logger.warning(
                    "share URL is read-only and no composer found; "
                    "falling back to chatgpt.com/"
                )
                try:
                    self._page.goto(
                        "https://chatgpt.com/",
                        wait_until="domcontentloaded",
                    )
                    self._page.wait_for_timeout(2_000)
                except PlaywrightError as exc:
                    logger.error("fallback navigation failed: %s", exc)

        # Otherwise: stay on whatever chat is open (last one used).
        # No new-chat click — keeps the run inside one conversation.

    # Hosts where the script is allowed to land top-level documents.
    # Sub-resources (img/css/font/api) are not restricted — only the
    # main frame's navigated URL.
    _ALLOWED_HOSTS: Final[tuple[str, ...]] = (
        "chatgpt.com",
        "chat.openai.com",
        "auth0.openai.com",   # ChatGPT login redirect
        "auth.openai.com",    # newer login host
    )

    @classmethod
    def _host_is_allowed(cls, url: str) -> bool:
        """True iff *url*'s host is in the allowlist (or a subdomain).
        Empty / ``about:blank`` / ``data:`` URLs are treated as safe
        because Playwright opens an about:blank tab on launch and we
        do not want to abort that."""
        if not url or url.startswith(("about:", "data:", "chrome:", "chrome-error:")):
            return True
        try:
            from urllib.parse import urlparse
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            return False
        if not host:
            return False
        for allowed in cls._ALLOWED_HOSTS:
            if host == allowed or host.endswith("." + allowed):
                return True
        return False

    def _install_navigation_guard(self) -> None:
        """Abort top-frame navigation to any non-allowlisted host.

        Why: when running against the user's personal Brave profile,
        a redirect to evil.example.com would expose the user's full
        cookie jar to that host (because Playwright reuses the real
        DPAPI-decryptable cookies). Aborting the document request
        before the browser ever sends cookies prevents that. The
        guard only fires for top-frame navigation — sub-resources
        (chatgpt's CDN / fonts / metrics) keep loading normally.
        """
        page = self._page
        if page is None:
            return

        def _maybe_block(route, request):
            try:
                # Only inspect top-frame document requests.
                rtype = request.resource_type
                is_main = (
                    request.is_navigation_request()
                    and rtype == "document"
                )
                if is_main:
                    if not self._host_is_allowed(request.url):
                        logger.error(
                            "navigation guard: BLOCKED top-frame nav to %r",
                            request.url[:200],
                        )
                        try:
                            route.abort()
                            return
                        except PlaywrightError:
                            pass
            except Exception as exc:  # noqa: BLE001 — never raise from a route hook
                logger.debug("nav-guard hook error (continuing): %s", exc)
            try:
                route.continue_()
            except PlaywrightError:
                pass

        try:
            self._context.route("**/*", _maybe_block)
        except PlaywrightError as exc:
            logger.warning(
                "could not install navigation guard: %s — running unguarded",
                exc,
            )

    # `_sync_auth_from_brave` was removed 2026-05-01: the strategy was
    # already abandoned (DPAPI keys are bound to the source profile so
    # copies decrypt blank), but the dead code still read & copied
    # the user's Cookies / Login Data DBs. Removing it eliminates an
    # unnecessary read of those secrets and prevents future
    # maintainers from re-enabling a path that doesn't actually work.

    def _close_browser(self) -> None:
        # CDP attach mode: leave the underlying Brave running and only
        # close the single tab we opened. The user's existing tabs are
        # NEVER touched. Then sweep any leftover about:blank /
        # chrome://newtab tabs.
        if self._cdp_attached:
            try:
                if self._page is not None:
                    try:
                        self._page.close()
                    except PlaywrightError:
                        pass
                    self._page = None
                # Final orphan-tab sweep before disconnecting so the
                # user's tab strip stays as clean as we found it.
                try:
                    self._cleanup_orphan_tabs()
                except PlaywrightError:
                    pass
            finally:
                if self._cdp_browser is not None:
                    try:
                        self._cdp_browser.close()
                    except PlaywrightError:
                        pass
                if self._playwright is not None:
                    try:
                        self._playwright.stop()
                    except PlaywrightError:
                        pass
                self._context = None
                self._page = None
                self._playwright = None
                self._cdp_browser = None
                self._cdp_attached = False
            return

        # Launched mode (we own the Brave instance) — close every page,
        # then the context, so nothing reappears in the user's session
        # restore on their next manual Brave open.
        try:
            if self._context is not None:
                try:
                    for pg in list(self._context.pages):
                        try:
                            pg.close()
                        except PlaywrightError:
                            pass
                except PlaywrightError:
                    pass
                try:
                    self._context.close()
                except PlaywrightError:
                    pass
        finally:
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except PlaywrightError:
                    pass
            self._context = None
            self._page = None
            self._playwright = None

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _send_prompt(self, text: str) -> None:
        assert self._page is not None
        # ChatGPT composer is a contenteditable div. Try a few selectors.
        composer = None
        for sel in (
            "#prompt-textarea",
            "div[contenteditable='true']",
            "textarea[placeholder*='メッセージ']",
            "textarea[placeholder*='message' i]",
            "textarea[placeholder*='質問してみましょう']",
        ):
            loc = self._page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                composer = loc
                break
        if composer is None:
            raise PlaywrightError("ChatGPT composer not found")

        # 2026-05-08 — composer focus + insert reliability hardening.
        # Symptom: `keyboard.insert_text(text)` after a bare `composer.click()`
        # occasionally landed in nowhere (composer ended up empty), which
        # then prevented the send-button from rendering and the whole
        # batch fell back to Unsplash. Three fixes:
        #   1. Disable voice-input mode if active (user ChatGPT settings
        #      may default to voice; the bottom-right "音声を使用する"
        #      icon then OCCUPIES the area where send button would render).
        #   2. Re-click + scroll-into-view to guarantee focus.
        #   3. After insertion, verify the composer's innerText is non-empty
        #      and retry with `fill()` on contenteditable / textarea if not.
        # Step 1 — force text mode (no-op if already in text mode).
        try:
            voice_btn = self._page.locator(
                "button[aria-label*='音声' i], "
                "button[aria-label*='voice' i], "
                "button[data-testid='voice-mode-button']"
            ).first
            if voice_btn.count() > 0 and voice_btn.is_visible():
                # Pressed/aria-pressed indicates active voice mode.
                pressed = (voice_btn.get_attribute("aria-pressed") or "").lower()
                if pressed == "true":
                    voice_btn.click()
                    logger.info("disabled voice-input mode (was active)")
                    self._page.wait_for_timeout(500)
        except PlaywrightError as exc:
            logger.debug("voice-mode probe skipped: %s", exc)

        composer.scroll_into_view_if_needed()
        composer.click()
        try:
            self._page.keyboard.insert_text(text)
        except PlaywrightError as exc:
            logger.warning(
                "insert_text failed (%s) — falling back to type()",
                exc,
            )
            composer.type(text, delay=1)

        # Verify text actually landed. ProseMirror sometimes drops content
        # if focus shifted between click() and insert_text. Self-heal once.
        try:
            cur = (composer.evaluate("el => el.innerText || el.value || ''") or "").strip()
        except PlaywrightError:
            cur = ""
        if len(cur) < min(20, len(text) // 4):
            logger.warning(
                "composer content too short after insert (got %d chars, want %d) — retrying via fill()",
                len(cur), len(text),
            )
            try:
                composer.fill("")
                composer.fill(text)
            except PlaywrightError:
                # Last-ditch: re-click and retype.
                composer.click()
                self._page.keyboard.insert_text(text)

        # 2026-05-08 user-suggested submission order: focus composer
        # then press Enter — this is the simplest path that works on
        # current ChatGPT UI (plain Enter submits, Shift+Enter adds
        # newline). Button-click stays as a fallback for very old UI
        # revs where Enter inserts newline.
        #
        # Verify submission by polling the composer — if its innerText
        # clears, we know the prompt was accepted. If not, escalate
        # through the fallback chain.
        def _composer_text() -> str:
            try:
                return (
                    composer.evaluate("el => el.innerText || el.value || ''")
                    or ""
                ).strip()
            except PlaywrightError:
                return "<unreadable>"

        sent = False
        # Primary: focus composer + press Enter.
        try:
            composer.click()  # re-focus in case voice-probe shifted it
            self._page.keyboard.press("Enter")
            self._page.wait_for_timeout(700)
            if not _composer_text():
                sent = True
                logger.info("sent via Enter (composer cleared)")
        except PlaywrightError as exc:
            logger.debug("Enter primary failed: %s", exc)

        # Secondary: send button via multiple selectors.
        if not sent:
            send_selectors = (
                "button[data-testid='send-button']",
                "button[aria-label='プロンプトを送信する']",
                "button[aria-label*='送信']",
                "button[aria-label='Send prompt']",
                "button[aria-label*='Send' i]",
                "form button[type='submit']:not([disabled])",
            )
            for sel in send_selectors:
                btn = self._page.locator(sel).first
                try:
                    btn.wait_for(state="visible", timeout=3_000)
                except PlaywrightTimeoutError:
                    continue
                try:
                    btn.click()
                    self._page.wait_for_timeout(500)
                    if not _composer_text():
                        sent = True
                        logger.info("sent via send button (sel=%s)", sel)
                        break
                except PlaywrightError as exc:
                    logger.debug("send click failed sel=%s exc=%s", sel, exc)
                    continue

        # Tertiary: Ctrl+Enter (forces send when Enter inserts newline
        # on some legacy UI revisions).
        if not sent:
            try:
                composer.click()
                self._page.keyboard.press("Control+Enter")
                self._page.wait_for_timeout(700)
                if not _composer_text():
                    sent = True
                    logger.info("sent via Ctrl+Enter fallback")
            except PlaywrightError as exc:
                logger.warning("Ctrl+Enter fallback failed: %s", exc)

        if not sent:
            logger.warning(
                "all submission paths failed — composer still has text=%r",
                _composer_text()[:60],
            )

        logger.info("ChatGPT prompt sent (%d chars)", len(text))
        # Confirm the composer cleared (UI flushes input on send).
        self._page.wait_for_timeout(1_500)

    def _wait_for_image(
        self,
        skip_urls: Optional[set[str]] = None,
    ) -> Optional[str]:
        """Poll the page for a generated image in the latest assistant turn.

        ChatGPT renders generated images in several possible shapes
        depending on UI version: a bare <img> inside the assistant
        message, an <img> inside a <figure>, or a background-image on
        a thumbnail wrapper. We try the broadest selector first and
        fall back as needed.

        Args:
            skip_urls: When non-empty, ignore images whose ``src`` is
                already in this set. Required for batch mode where the
                previous image is still rendered in the DOM and would
                otherwise be returned again.

        Returns the image src URL, or None if the model didn't produce
        one within ``_IMAGE_WAIT_TIMEOUT``.
        """
        assert self._page is not None
        deadline = time.time() + _IMAGE_WAIT_TIMEOUT / 1000
        skip_list = list(skip_urls or set())

        # Strategy: limit the search to the LAST assistant turn — i.e.
        # the message bubble created by the prompt we just sent. Falls
        # back to the whole document if no assistant turn exists yet.
        # This is the divergence-prevention fix from 2026-05-01: prior
        # turns (cached in the fixed share-URL chat) had K-beauty/etc.
        # images that were being picked up as if they were the new
        # generation. Even with skip_urls a stale image could win if
        # we forgot to seed it. Scoping to the newest turn closes that
        # whole class of bugs.
        # Pass skip_list via Playwright's second-arg serializer rather
        # than %-formatting it into the JS source — that avoids JS
        # injection / quote-escape bugs when ChatGPT image URLs contain
        # exotic characters.
        select_js = """(skipArr) => {
            const skip = new Set(skipArr || []);
            const turns = document.querySelectorAll(
                '[data-message-author-role="assistant"]'
            );
            const root = turns.length
                ? turns[turns.length - 1]
                : document;
            const imgs = Array.from(root.querySelectorAll('img'));
            const candidates = imgs
                .map(img => ({
                    src: img.src,
                    w: img.naturalWidth || img.width || 0,
                    h: img.naturalHeight || img.height || 0,
                    alt: img.alt,
                }))
                .filter(o =>
                    o.src
                    && (o.src.startsWith('https://') || o.src.startsWith('blob:'))
                    && o.w >= 200
                    && o.h >= 200
                    && !/avatar|sprite|emoji|icon/.test(o.src)
                    && !skip.has(o.src)
                )
                .sort((a, b) => (b.w * b.h) - (a.w * a.h));
            return candidates.length ? candidates[0].src : null;
        }"""
        while time.time() < deadline:
            try:
                src = self._page.evaluate(select_js, skip_list)
            except PlaywrightError:
                src = None
            if src:
                # Stabilise: in-progress images sometimes flicker URLs.
                stable_for = 0
                last_src = src
                while time.time() < deadline:
                    self._page.wait_for_timeout(1_000)
                    try:
                        # Reuse the same skip-aware selector so we keep
                        # tracking only the freshly-generated image.
                        new_src = self._page.evaluate(select_js, skip_list)
                    except PlaywrightError:
                        new_src = None
                    if new_src == last_src:
                        stable_for += 1
                        if stable_for >= 2:
                            logger.info(
                                "ChatGPT image URL stabilised: %s",
                                last_src[:80],
                            )
                            return last_src
                    else:
                        stable_for = 0
                        last_src = new_src or last_src
                return last_src
            self._page.wait_for_timeout(1_500)

        # Timeout — capture a screenshot so we can see what went wrong.
        try:
            shot = (
                _REPO_ROOT / "data" / "images" / "covers"
                / f"chatgpt_timeout_{int(time.time())}.png"
            )
            shot.parent.mkdir(parents=True, exist_ok=True)
            self._page.screenshot(path=str(shot), full_page=True)
            logger.error("Timeout screenshot saved to %s", shot)
            # Also dump the latest assistant message HTML for debugging.
            html_dump = shot.with_suffix(".html")
            try:
                latest = self._page.locator(
                    "[data-message-author-role='assistant']"
                ).last
                if latest.count() > 0:
                    html_dump.write_text(
                        latest.inner_html(), encoding="utf-8",
                    )
                    logger.error("Latest assistant HTML: %s", html_dump)
            except PlaywrightError:
                pass
        except PlaywrightError as exc:
            logger.error("Failed to take timeout screenshot: %s", exc)
        return None

    def _download_via_browser(self, url: str, dest: Path) -> None:
        """Download the image through Playwright so cookies are sent.

        ChatGPT serves images from /backend-api/estuary/content which
        rejects unauthenticated requests with 403. The browser context
        already has the right session cookies, so we proxy the GET
        through page.evaluate + fetch().
        """
        assert self._page is not None
        # Use the page context's fetch — same origin, cookies attached.
        b64 = self._page.evaluate(
            """async (url) => {
                const r = await fetch(url, { credentials: 'include' });
                if (!r.ok) {
                    throw new Error('HTTP ' + r.status);
                }
                const buf = await r.arrayBuffer();
                let binary = '';
                const bytes = new Uint8Array(buf);
                for (let i = 0; i < bytes.byteLength; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                return btoa(binary);
            }""",
            url,
        )
        import base64 as _b64
        data = _b64.b64decode(b64)
        dest.write_bytes(data)
        logger.info(
            "ChatGPT image saved: %s (%d bytes)", dest, dest.stat().st_size,
        )

    @staticmethod
    def _download(url: str, dest: Path) -> None:  # legacy / fallback
        resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        logger.info(
            "ChatGPT image saved (plain GET): %s (%d bytes)",
            dest, dest.stat().st_size,
        )
