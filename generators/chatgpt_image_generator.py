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

# Files (relative to Default/) we copy to inherit the ChatGPT login.
# Modern Chromium puts cookies under Default/Network/. Local Storage /
# IndexedDB cover the auth tokens ChatGPT stores on the SPA side.
_AUTH_FILES: Final[tuple[str, ...]] = (
    "Network/Cookies",
    "Network/Cookies-journal",
    "Network/TransportSecurity",
    "Preferences",
    "Login Data",
    "Login Data For Account",
)
_AUTH_DIRS: Final[tuple[str, ...]] = (
    "Local Storage",
    "IndexedDB",
    "Session Storage",
)

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


def _resolve_chat_url() -> str:
    if _CHAT_URL_CACHE_FILE.exists():
        cached = _CHAT_URL_CACHE_FILE.read_text(encoding="utf-8").strip()
        if cached:
            return cached
    env = os.environ.get("CHATGPT_IMAGE_CHAT_URL")
    if env:
        return env
    return "https://chatgpt.com/"


_CHATGPT_NEW_CHAT: Final[str] = _resolve_chat_url()

_NAV_TIMEOUT: Final[int] = 60_000
# Image generation takes 30-90s typically. Cap at 4min to recover.
_IMAGE_WAIT_TIMEOUT: Final[int] = 240_000

# Text-reply waiting (used by Vision evaluation). ChatGPT typically
# answers a 2-line scoring prompt in 5-15s; cap at 60s.
_TEXT_WAIT_TIMEOUT: Final[int] = 60_000

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
    """``CHATGPT_VISION_EVAL`` toggle. Default off (opt-in)."""
    val = os.environ.get("CHATGPT_VISION_EVAL", "").strip().lower()
    return val in {"1", "true", "yes", "on"}

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_batch(
        self,
        prompts: list[str],
        size: Size = "landscape",
        out_paths: Optional[list[Path]] = None,
        topic: str = "",
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
        seen_urls: set[str] = set()
        eval_on = _vision_eval_enabled()
        try:
            self._open_browser()
            for i, (prompt, dest) in enumerate(zip(prompts, out_paths)):
                logger.info(
                    "batch image %d/%d", i + 1, len(prompts),
                )
                # Convention from publish_custom_post.py: prompts[0] is
                # the article cover, rest are inline section visuals.
                is_cover = (i == 0)
                full_prompt = self._build_prompt(
                    prompt, size, is_cover=is_cover,
                )
                try:
                    self._send_prompt(full_prompt)
                    img_url = self._wait_for_image(skip_urls=seen_urls)
                    if not img_url:
                        logger.error("batch %d: no image found", i + 1)
                        continue
                    seen_urls.add(img_url)
                    self._download_via_browser(img_url, dest)
                    results[i] = dest

                    if eval_on and topic:
                        kind = "サムネ" if is_cover else "インライン"
                        if not self._image_passes_vision_eval(
                            topic=topic, kind=kind,
                        ):
                            # One retry: ask for a fresh image with
                            # explicit "前回はズレていた" feedback so the
                            # model adjusts. The skip_urls guard ensures
                            # we wait for a new URL, not the rejected one.
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
                                    self._download_via_browser(new_url, dest)
                                    results[i] = dest
                            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                                logger.warning(
                                    "batch %d retry failed: %s — "
                                    "keeping original",
                                    i + 1, exc,
                                )
                except (PlaywrightTimeoutError, PlaywrightError) as exc:
                    logger.error("batch %d failed: %s", i + 1, exc)
                    continue
            # All prompts processed (or skipped) — soft-delete the
            # personal /c/<id> chat we created so the user's sidebar
            # 「最近」section doesn't fill up with one entry per run.
            try:
                self._delete_current_chat()
            except PlaywrightError as exc:
                logger.warning("delete current chat failed: %s", exc)
        finally:
            self._close_browser()
        return results

    # ------------------------------------------------------------------
    # Vision evaluation (opt-in via CHATGPT_VISION_EVAL=1)
    # ------------------------------------------------------------------

    def _image_passes_vision_eval(self, topic: str, kind: str) -> bool:
        """Ask ChatGPT to score the most-recent image vs the article topic.

        Sends a short scoring prompt, waits for the text reply, parses
        the SCORE: <n> line, and returns True iff n >= cutoff. Any
        failure (timeout, parse miss, browser error) returns True so
        we don't tank a perfectly fine generation on infrastructure
        flake — Vision eval is supplementary, not load-bearing.
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
                logger.info("vision-eval: no reply parseable; pass-through")
                return True
            score = self._parse_vision_score(reply)
            if score is None:
                logger.info(
                    "vision-eval: SCORE not parseable from %r — pass-through",
                    reply[:120],
                )
                return True
            ok = score >= _VISION_EVAL_CUTOFF
            logger.info(
                "vision-eval: score=%d cutoff=%d → %s",
                score, _VISION_EVAL_CUTOFF, "PASS" if ok else "FAIL",
            )
            return ok
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            logger.warning("vision-eval browser error: %s — pass-through", exc)
            return True

    def _wait_for_text_reply(self) -> Optional[str]:
        """Wait for ChatGPT's latest assistant turn to finish streaming.

        Polls innerText of the last ``[data-message-author-role='assistant']``
        element. Considers the turn done when the text has not changed
        for 2 consecutive polls (1 sec each) — ChatGPT streams tokens
        every ~50 ms during generation so a 2-sec stable read means
        generation has stopped.
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
        last_text = ""
        stable_for = 0
        while time.time() < deadline:
            try:
                cur = self._page.evaluate(select_js) or ""
            except PlaywrightError:
                cur = ""
            if cur and cur == last_text:
                stable_for += 1
                if stable_for >= 2 and len(cur) > 0:
                    return cur
            else:
                stable_for = 0
                last_text = cur
            self._page.wait_for_timeout(1_000)
        return last_text or None

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
    def _build_prompt(prompt: str, size: Size, is_cover: bool = False) -> str:
        """Compose the imperative prompt sent to ChatGPT (Japanese).

        Format requested by the user (2026-04-28):
          1. 「この記事のサムネ/インライン画像を作成してください」
          2. 記事の要約 (prompt argument is the JP summary of the
             article, produced by visual_prompt_builder)
          3. サイズ指定
          4. 宮崎駿/新海誠/細田守風で生成 — 最後に明示
             (「スタジオジブリ」直書きは2026-04-28以降ChatGPTがブロック)
          5. 全部日本語

        ``is_cover`` switches the noun between サムネイル / インライン.
        """
        kind = "サムネイル画像" if is_cover else "インライン画像"
        # 2026-04-28: 「スタジオジブリ風」直書きが OpenAI の第三者コンテンツ
        # モデレーションに引っかかるようになったので、商標名を外して
        # 個人クリエイター名 + テクニカルな描写語に分散。日本のアニメ
        # 監督 (宮崎駿/新海誠/細田守) の名前なら個人芸術家として通る。
        return (
            f"以下の記事の{kind}を作成してください。\n"
            f"プロンプトを返さず、実際に画像を生成して返してください。\n\n"
            f"【記事の内容】\n"
            f"{prompt}\n\n"
            f"【サイズ】\n"
            f"{_SIZE_PHRASE[size]}\n\n"
            f"【スタイル】\n"
            f"宮崎駿、新海誠、細田守のような日本のアニメ監督の作風を参考に、\n"
            f"温かみのある手描き水彩アニメーション調で生成してください。\n"
            f"- 手描き水彩タッチ、優しいパステルカラー、温かい光\n"
            f"- 夢幻的・ノスタルジックな雰囲気、自然光\n"
            f"- キャラクターや自然背景・建物が登場してOK\n"
            f"- テキスト・読める文字・ロゴ・透かし・UIスクリーンショットは描かない\n"
            f"- 中央に被写体を配置、シネマティックな構図\n\n"
            f"出力は画像のみ。前置き・後置きの文章は不要です。"
        )

    def generate(
        self,
        prompt: str,
        size: Size = "landscape",
        out_path: Optional[Path] = None,
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

        full_prompt = self._build_prompt(prompt, size)

        try:
            self._open_browser()
            self._send_prompt(full_prompt)
            img_url = self._wait_for_image()
            if not img_url:
                logger.error("ChatGPT image generation: no image element found")
                return None
            # ChatGPT-served images require the same cookies used to load
            # the page (the URL is /backend-api/estuary/content with a
            # signed query plus session auth). Download via Playwright
            # so the request inherits the browser context.
            self._download_via_browser(img_url, out_path)
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
        # Strategy: use Brave's actual User Data dir directly. Cookies
        # are encrypted with Windows DPAPI keys stored in Local State
        # — copying selected files alone won't preserve decryptability,
        # so the copy strategy was abandoned in favour of reusing the
        # real profile. Brave **must be closed** for this to work
        # (otherwise the user_data_dir is locked).
        # Profile changes during automation are limited to the chat
        # history (one new conversation per image). To avoid history
        # pollution we delete the conversation right after extraction
        # in a future revision; for now the cost is one ephemeral
        # row in the user's chat list per image.
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
                        # runs skip the share-redirect dance.
                        if "/c/" in new_url:
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

    def _sync_auth_from_brave(self) -> None:
        """Copy auth files from the user's real Brave profile.

        Idempotent and fast — just overwrites the auth artifacts inside
        our isolated profile dir. The source ``Default`` profile may be
        in use (Brave running) but Windows allows reading these files
        even when locked, so the copy succeeds.
        """
        import shutil
        src_default = _BRAVE_USER_DATA / "Default"
        if not src_default.exists():
            logger.warning(
                "Brave default profile not found at %s — assuming "
                "isolated profile already has a login.",
                src_default,
            )
            return
        dst_default = self._profile_dir / "Default"
        dst_default.mkdir(parents=True, exist_ok=True)
        # Always copy Local State (sits at User Data root).
        local_state_src = _BRAVE_USER_DATA / "Local State"
        if local_state_src.exists():
            try:
                shutil.copy2(local_state_src, self._profile_dir / "Local State")
            except OSError as exc:
                logger.debug("Local State copy skipped: %s", exc)
        for fname in _AUTH_FILES:
            src = src_default / fname
            if src.exists():
                dst = dst_default / fname
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(src, dst)
                except OSError as exc:
                    logger.debug("auth file copy skipped (%s): %s", fname, exc)
        for dname in _AUTH_DIRS:
            src = src_default / dname
            dst = dst_default / dname
            if src.exists():
                try:
                    if dst.exists():
                        shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                except OSError as exc:
                    logger.debug("auth dir copy skipped (%s): %s", dname, exc)
        logger.info(
            "synced auth files from Brave Default → %s", self._profile_dir,
        )

    def _close_browser(self) -> None:
        # Explicitly close every page first. Without this, pages we
        # opened (including the implicit about:blank that Playwright
        # creates when launching Brave) get persisted in the user's
        # Brave session-restore data and reappear next time they open
        # the browser manually. Closing one-by-one prevents that.
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
        ):
            loc = self._page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                composer = loc
                break
        if composer is None:
            raise PlaywrightError("ChatGPT composer not found")

        composer.click()
        composer.type(text, delay=10)
        # The send button only renders once the composer has content.
        # Wait for it explicitly — Enter as a fallback can be misread
        # as "newline" in contenteditable on some UI revisions.
        sent = False
        send_btn = self._page.locator(
            "button[data-testid='send-button']"
        ).first
        try:
            send_btn.wait_for(state="visible", timeout=8_000)
            send_btn.click()
            sent = True
            logger.info("clicked send button (data-testid=send-button)")
        except PlaywrightTimeoutError:
            logger.warning("send-button did not become visible in 8s")
        except PlaywrightError as exc:
            logger.warning("send-button click failed: %s", exc)
        if not sent:
            # Last-resort: try Ctrl+Enter (forces send even when Enter
            # inserts newline) then plain Enter.
            try:
                self._page.keyboard.press("Control+Enter")
                sent = True
                logger.info("sent via Ctrl+Enter fallback")
            except PlaywrightError:
                self._page.keyboard.press("Enter")
                logger.info("sent via Enter fallback")
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
        skip = skip_urls or set()
        skip_js_array = "[" + ",".join(
            f"'{u}'" for u in skip if "'" not in u
        ) + "]"

        # Strategy: poll all <img> elements in the document and pick the
        # one that (a) has a real https/blob src, (b) renders larger
        # than 200×200 px (filters icons, avatars, sprites), and (c) is
        # not in the skip set (so batch mode advances past prior images).
        # The generated image is by far the largest visual element added
        # to the DOM after we send.
        select_js = """() => {
            const skip = new Set(%s);
            const imgs = Array.from(document.querySelectorAll('img'));
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
        }""" % skip_js_array
        while time.time() < deadline:
            try:
                src = self._page.evaluate(select_js)
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
                        new_src = self._page.evaluate(select_js)
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
