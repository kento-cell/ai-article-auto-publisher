"""Gemini (gemini.google.com) image generator via Playwright + Brave CDP.

Drop-in backend replacement for :class:`ChatGPTImageGenerator` when
``USE_GEMINI_IMAGES=1`` is set. Reason for existence: the user's ChatGPT
Plus subscription was cancelled on 2026-07-15, so the ChatGPT image path
gets throttled to ~2-3 images/day on Free tier — insufficient for the
daily 4-article × 4-5 image batch.

Gemini 3.5 Flash generates images natively when the prompt starts with
「画像を生成してください:」 (verified 2026-07-02 PoC). The image lands in
the DOM as a ``blob:`` URL with naturalWidth >= 512; we grab it via
canvas.toDataURL to bypass fetch()'s cross-origin CORS barrier.

2026-07-02 audit fixes (v2):

* Newlines in the effective prompt are flattened to spaces before
  ``keyboard.type`` — a literal ``\\n`` is typed as an Enter *keypress*
  which submits the half-typed prompt (multi-line style_blocks made
  this a guaranteed failure; the v1 dry-run only passed because the
  ghibli path had no style_block).
* The cover slot now gets the same click-bait infographic-banner
  treatment as ChatGPTImageGenerator._build_prompt(is_cover=True) —
  v1 sent the raw prompt so covers lost the「文字入り煽りサムネ」
  identity entirely.
* ``size`` is honoured via an explicit aspect-ratio directive
  (v1 ignored it and relied on Gemini's default being landscape).
* ``_extract_png`` targets the exact blob URL found by the waiter
  instead of re-querying for "any big blob img".
* Best-effort per-image chat deletion (``GEMINI_CLEANUP_CHATS``,
  default ON) — mirrors the ChatGPT per-image session-delete policy:
  article titles/content must not accumulate in the Gemini sidebar.

Public API mirrors ChatGPTImageGenerator so chatgpt_batch_helper.py can
just swap backends behind USE_GEMINI_IMAGES.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

logger = logging.getLogger(__name__)

_GEMINI_URL = "https://gemini.google.com/app"
_MIN_VALID_IMAGE_BYTES = 10_000

# When Gemini finishes rendering the image, an <img> with
# blob:https://gemini.google.com/... appears whose naturalWidth is at
# least 512. Poll until we see one or hit this timeout.
_GEN_TIMEOUT_SECONDS = 90
_POLL_INTERVAL_MS = 1500

# Aspect-ratio directives appended to every prompt. Gemini has no size
# API; the natural-language directive is the only control we have. The
# v1 dry-run happened to return 1024x559 by default but that is not
# guaranteed across model updates.
_SIZE_PHRASE: dict[str, str] = {
    "landscape": "アスペクト比 16:9 の横長で生成してください。",
    "portrait": "アスペクト比 9:16 の縦長で生成してください。",
    "square": "アスペクト比 1:1 の正方形で生成してください。",
}

# Inline-image default style — mirrors ChatGPTImageGenerator's
# default_style (ghibli watercolor). Kept in sync manually; if you
# change one, change the other.
_DEFAULT_STYLE = (
    "宮崎駿、新海誠、細田守のような日本のアニメ監督の作風を参考に、"
    "温かみのある手描き水彩アニメーション調で。"
    "手描き水彩タッチ、優しいパステルカラー、温かい光、"
    "夢幻的・ノスタルジックな雰囲気。"
    "テキスト・読める文字・ロゴ・透かし・UIスクリーンショットは描かない。"
    "中央に被写体を配置、シネマティックな構図。"
)


def _is_cleanup_enabled() -> bool:
    """``GEMINI_CLEANUP_CHATS`` toggle (default ON).

    Mirrors the ChatGPT per-image session-delete policy (memory:
    画像生成で作った会話は必ず削除 — article titles and section text
    otherwise accumulate in the Gemini sidebar history).
    """
    val = os.environ.get("GEMINI_CLEANUP_CHATS", "1").strip().lower()
    return val not in {"", "0", "false", "no", "off"}


def _flatten(text: str) -> str:
    """Collapse all whitespace runs (incl. newlines) to single spaces.

    ``page.keyboard.type`` interprets a literal newline as an Enter
    keypress, which submits the half-typed prompt in Gemini. Prompts
    assembled from multi-line style_blocks MUST pass through here.
    """
    return re.sub(r"\s+", " ", text).strip()


class GeminiImageGenerator:
    """Playwright-backed Gemini image gen (CDP attach to Brave).

    Same contract as ChatGPTImageGenerator: ``generate_batch(prompts,
    size, out_paths, topic=?, style_block=?, cover_styled=?)`` returns
    ``list[Path | None]`` (None per slot on failure). Callers already
    handle None by falling through to Pollinations / Unsplash.
    """

    def __init__(self, headless: bool = False) -> None:
        # headless is accepted for interface parity with the ChatGPT
        # generator but ignored — we attach to a live Brave instance
        # via CDP, so window visibility is controlled by the browser.
        _ = headless
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def _start(self) -> None:
        port_str = os.environ.get("CHATGPT_CDP_PORT", "9222").strip()
        try:
            port = int(port_str)
        except ValueError:
            raise RuntimeError(f"invalid CHATGPT_CDP_PORT: {port_str!r}")

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}",
            )
        except PlaywrightError as exc:
            self._playwright.stop()
            self._playwright = None
            raise RuntimeError(
                f"connect_over_cdp to Brave at port {port} failed: {exc}",
            ) from exc

        contexts = self._browser.contexts
        if not contexts:
            self._context = self._browser.new_context()
        else:
            # Reuse the existing (user-logged-in) context so the Google
            # session cookies are already loaded.
            self._context = contexts[0]
        # NOTE: no page here — _navigate_fresh_chat opens one per image.

    def close(self) -> None:
        # Do NOT close self._context / self._browser: in CDP-attach mode
        # they belong to the user's live Brave session — closing the
        # context would close the user's real windows.
        if self._page is not None:
            try:
                self._page.close()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
        self._playwright = None
        self._page = None
        self._context = None
        self._browser = None

    # ------------------------------------------------------------------
    # Prompt composition (mirrors ChatGPTImageGenerator._build_prompt)
    # ------------------------------------------------------------------
    @staticmethod
    def _compose_prompt(
        raw_prompt: str,
        *,
        is_cover: bool,
        size: str,
        style_block: str | None,
        cover_styled: bool,
    ) -> str:
        """Build the full Gemini prompt for one slot.

        Three branches, same as the ChatGPT builder:

        1. cover + cover_styled + style_block → styled cover (the
           preset carries the look).
        2. cover (default) → click-bait infographic banner with large
           Japanese title text — the thumbnail is the click-driver.
        3. inline → subject illustration in style_block or the default
           ghibli watercolor. Calm complement to the body text.

        The returned string still contains newlines for readability;
        the caller flattens it before typing.
        """
        size_phrase = _SIZE_PHRASE.get(size, _SIZE_PHRASE["landscape"])
        if is_cover and cover_styled and style_block:
            return (
                f"画像を生成してください: note記事のサムネイル画像 1枚。"
                f"{size_phrase} "
                f"描いてほしいシーン: {raw_prompt} "
                f"スタイル指定: {style_block} "
                f"テキスト・読める文字・ロゴ・透かしは描かない。"
                f"出力は画像1枚のみ、前置き・質問は不要。"
            )
        if is_cover:
            # 煽動的・文字入りサムネ (ChatGPT 版 2026-05-07 と同一方針)。
            # Gemini (Imagen 系) は日本語テキスト描画が ChatGPT (DALL-E/
            # gpt-image) より不安定なので、キーワードを 3-5 語に絞る指示を
            # 強調している。
            return (
                f"画像を生成してください: note記事のアイキャッチ・サムネ画像 1枚。"
                f"{size_phrase} "
                f"目的: クリック率を最大化する煽動的・文字入りバナー。 "
                f"メインキャッチ文字を画像中央〜上部に巨大な日本語極太ゴシック体で描く: "
                f"「{raw_prompt[:60]}」 の主要キーワード3〜5語を抜き出して"
                f"一番大きく目立つように。 "
                f"強コントラスト配色 (黒地+白文字 / 赤地+黄文字 など)、"
                f"縁取り+ドロップシャドウで文字はくっきり読めること。 "
                f"左右どちらかに表情豊かなアニメ風キャラ or 象徴イラストを大きく配置し"
                f"視線を文字に誘導。 "
                f"背景はビビッドな単色 or 2色グラデ + 集中線・きらめき等の装飾1-2個。 "
                f"YouTube サムネ・雑誌の煽り広告型のインフォグラフィック構図。 "
                f"既存IPの商標ロゴ・実在キャラの直接描写は避ける。 "
                f"出力は画像1枚のみ、前置き・質問は不要。"
            )
        style = style_block if style_block else _DEFAULT_STYLE
        return (
            f"画像を生成してください: 記事のインライン挿絵 1枚。"
            f"{size_phrase} "
            f"記事の被写体・場面（これをそのまま描いてください）: {raw_prompt} "
            f"スタイル指定: {style} "
            f"出力は画像1枚のみ、前置き・質問は不要。"
        )

    # ------------------------------------------------------------------
    # Per-image flow
    # ------------------------------------------------------------------
    def _navigate_fresh_chat(self) -> bool:
        """Open a brand-new tab for every image so Gemini's SPA state
        doesn't carry over between prompts, then switch into 一時チャット
        (temporary chat) so nothing is saved to the sidebar history.

        2026-07-02 dry-run showed that same-page ``goto(/app)`` between
        prompts leaves image-gen routing off for the 2nd+ prompt (only
        image #1 succeeded, #2 and #3 stayed in text mode and timed
        out). A fresh tab (new Page) fully resets SPA state and image
        routing re-engages on the ``画像を生成してください:`` trigger.

        2026-07-03 audit: 一時チャット mode verified to support image
        generation. It solves the history-leak problem structurally —
        prompts embed article titles/content, and temp chats are never
        persisted, so no fragile delete-flow automation is needed.
        Returns True when temp-chat mode was activated (caller skips
        the cleanup fallback in that case).
        """
        assert self._context is not None
        # Close prior page if any — keeps Chrome resource footprint down
        # across a 5-image batch.
        prior = self._page
        if prior is not None:
            try:
                prior.close()
            except Exception:  # noqa: BLE001
                pass
        # 2026-07-07: open the tab in the BACKGROUND via raw CDP.
        # Playwright's context.new_page() activates the new tab, which
        # steals the user's current tab for a moment when they are
        # actively using this Brave window. Target.createTarget with
        # background:true keeps the user's tab focused; we then adopt
        # the resulting Page object via expect_page(). Falls back to
        # new_page() if the CDP call fails (e.g. non-Chromium).
        page = None
        try:
            assert self._browser is not None
            session = self._browser.new_browser_cdp_session()
            with self._context.expect_page(timeout=10_000) as pinfo:
                session.send("Target.createTarget", {
                    "url": "about:blank",
                    "background": True,
                })
            page = pinfo.value
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "gemini: background tab create failed (%s) — "
                "falling back to foreground new_page()", exc,
            )
            page = self._context.new_page()
        self._page = page
        # Background tabs report document.hidden=true, and Gemini's SPA
        # may pause its generation polling on that signal. Spoof the
        # visibility API before any app script runs so the SPA behaves
        # as if the tab were foregrounded. (Timer throttling itself is
        # disabled via --disable-background-timer-throttling in
        # launch_brave_cdp.bat.)
        try:
            self._page.add_init_script(
                "Object.defineProperty(document, 'visibilityState',"
                " {get: () => 'visible'});"
                "Object.defineProperty(document, 'hidden',"
                " {get: () => false});"
                "document.addEventListener('visibilitychange',"
                " e => e.stopImmediatePropagation(), true);"
            )
        except Exception:  # noqa: BLE001
            pass
        self._page.goto(_GEMINI_URL, wait_until="domcontentloaded")
        self._page.wait_for_timeout(3500)
        # 留意点 (privacy notice) dialog appears on first load per Chrome
        # profile. Best-effort dismiss.
        try:
            ok = self._page.locator("button:has-text('OK')").first
            if ok.is_visible(timeout=1500):
                ok.click()
                self._page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001
            pass
        # Switch into temporary chat. aria-label verified 2026-07-03;
        # keep an English fallback for account-language drift.
        for sel in (
            "button[aria-label='一時チャット']",
            "button[aria-label*='Temporary chat']",
            "button[aria-label*='temporary chat']",
        ):
            try:
                btn = self._page.locator(sel).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    self._page.wait_for_timeout(2000)
                    return True
            except Exception:  # noqa: BLE001
                continue
        logger.warning(
            "gemini: 一時チャット button not found — falling back to a "
            "normal chat + post-generation delete",
        )
        return False

    def _send_prompt(self, prompt: str) -> bool:
        """Fill the Gemini textbox and press Enter. Returns True on
        successful send.

        ``prompt`` MUST already be newline-free (see :func:`_flatten`)
        — keyboard.type presses Enter for a literal ``\\n`` which would
        submit the half-typed prompt.
        """
        assert self._page is not None
        page = self._page
        selectors = [
            "div[contenteditable='true'][role='textbox']",
            "rich-textarea div[contenteditable='true']",
            "textarea[aria-label*='Gemini']",
            "textarea[placeholder*='Gemini']",
        ]
        entered = False
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=1500):
                    loc.click()
                    # Real keystrokes so React onChange fires (mirrors
                    # PoC-verified pattern; Gemini rejects programmatic
                    # value assignment silently).
                    page.keyboard.type(prompt, delay=8)
                    entered = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not entered:
            logger.error("gemini: prompt textbox not found")
            return False
        page.wait_for_timeout(350)
        try:
            page.keyboard.press("Enter")
        except PlaywrightError as exc:
            logger.warning("gemini: Enter press failed: %s", exc)
            return False
        return True

    def _wait_for_image(self) -> str | None:
        """Poll for a blob img element with naturalWidth >= 512. Returns
        the blob URL string, or None on timeout."""
        assert self._page is not None
        page = self._page
        deadline = time.time() + _GEN_TIMEOUT_SECONDS
        while time.time() < deadline:
            try:
                url = page.evaluate("""
                    () => {
                      const imgs = Array.from(document.querySelectorAll('img'));
                      const g = imgs.find(i => i.src.startsWith('blob:') && i.naturalWidth >= 512);
                      return g ? g.src : null;
                    }
                """)
            except PlaywrightError:
                url = None
            if url:
                return url
            page.wait_for_timeout(_POLL_INTERVAL_MS)
        return None

    def _extract_png(self, blob_url: str) -> bytes | None:
        """Read the generated image via canvas.toDataURL — bypasses
        fetch()'s CORS boundary against blob: URLs.

        Targets the exact ``blob_url`` the waiter found, so a stray
        second blob image (avatar previews, earlier attachments) can't
        be captured by mistake. Returns raw PNG bytes or None.
        """
        assert self._page is not None
        try:
            b64 = self._page.evaluate("""
                (blobUrl) => {
                  const img = Array.from(document.querySelectorAll('img'))
                    .find(i => i.src === blobUrl);
                  if (!img || img.naturalWidth < 512) return null;
                  const c = document.createElement('canvas');
                  c.width = img.naturalWidth;
                  c.height = img.naturalHeight;
                  const g = c.getContext('2d');
                  g.drawImage(img, 0, 0);
                  const dataUrl = c.toDataURL('image/png');
                  return dataUrl.split(',')[1] || null;
                }
            """, blob_url)
        except PlaywrightError as exc:
            logger.warning("gemini: canvas extract failed: %s", exc)
            return None
        if not b64:
            return None
        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError) as exc:
            logger.warning("gemini: base64 decode failed: %s", exc)
            return None

    def _cleanup_current_chat(self) -> bool:
        """Best-effort delete of the conversation just created.

        Mirrors the ChatGPT per-image session-delete policy: image
        prompts embed article titles/section text, and leaving them in
        the sidebar both leaks content and (in ChatGPT's case) polluted
        later generations via Memory. Never raises; returns True when
        the delete flow completed.

        Flow (current Gemini UI, DOM verified 2026-07-03): sidebar is
        COLLAPSED in a fresh tab, so first expand it via the
        ``side-nav-sparkle-button`` (aria-label サイドバーを開く). The
        freshly created conversation is then the first
        ``gem-nav-list-item[data-test-id='conversation']`` row. Hover
        it → actions button (⋮) → 削除 → confirm dialog 削除.

        NOTE: this is a FALLBACK — the primary privacy mechanism is
        一時チャット mode (see _navigate_fresh_chat), which never saves
        the conversation in the first place. This path only runs when
        the temp-chat button wasn't found.
        """
        assert self._page is not None
        page = self._page
        try:
            # Sidebar is collapsed in a fresh tab — conversation rows
            # exist in the DOM but are not visible until expanded.
            for sel in (
                "button[data-test-id='side-nav-sparkle-button']",
                "button[aria-label*='サイドバーを開く']",
                "button[aria-label*='Open sidebar']",
            ):
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=1200):
                        btn.click()
                        page.wait_for_timeout(1000)
                        break
                except Exception:  # noqa: BLE001
                    continue
            # The conversation list item (custom element, DOM verified
            # 2026-07-03: gem-nav-list-item[data-test-id='conversation']).
            row = None
            for sel in (
                "gem-nav-list-item[data-test-id='conversation']",
                "[data-test-id='conversation']",
                ".conversation",
            ):
                loc = page.locator(sel).first
                try:
                    if loc.is_visible(timeout=1500):
                        row = loc
                        break
                except Exception:  # noqa: BLE001
                    continue
            if row is None:
                logger.warning("gemini cleanup: no conversation row found")
                return False
            row.hover()
            page.wait_for_timeout(300)
            # The row's action menu button.
            menu_btn = None
            for sel in (
                "[data-test-id='actions-menu-button']",
                "button[aria-label*='アクション']",
                "button[aria-label*='その他']",
                "button[aria-label*='More']",
            ):
                loc = row.locator(sel).first
                try:
                    if loc.is_visible(timeout=800):
                        menu_btn = loc
                        break
                except Exception:  # noqa: BLE001
                    continue
            if menu_btn is None:
                # Menu button may be a sibling rendered on hover at the
                # page level rather than inside the row.
                loc = page.locator("button[aria-label*='アクション']").first
                try:
                    if loc.is_visible(timeout=800):
                        menu_btn = loc
                except Exception:  # noqa: BLE001
                    pass
            if menu_btn is None:
                logger.debug("gemini cleanup: actions menu button not found")
                return False
            menu_btn.click()
            page.wait_for_timeout(400)
            del_item = page.locator(
                "[role='menuitem']:has-text('削除'), "
                "button:has-text('削除')",
            ).first
            if not del_item.is_visible(timeout=1500):
                logger.debug("gemini cleanup: 削除 menu item not found")
                page.keyboard.press("Escape")
                return False
            del_item.click()
            page.wait_for_timeout(500)
            # Confirm dialog.
            confirm = page.locator(
                "[role='dialog'] button:has-text('削除'), "
                "mat-dialog-container button:has-text('削除')",
            ).first
            if confirm.is_visible(timeout=1500):
                confirm.click()
                page.wait_for_timeout(600)
            logger.info("gemini cleanup: chat deleted")
            return True
        except Exception as exc:  # noqa: BLE001 — never block the batch
            logger.debug("gemini cleanup failed (non-fatal): %s", exc)
            return False

    # ------------------------------------------------------------------
    # Public API (mirrors ChatGPTImageGenerator.generate_batch)
    # ------------------------------------------------------------------
    def generate_batch(
        self,
        prompts: list[str],
        size: str = "landscape",
        out_paths: list[Path] | None = None,
        topic: str | None = None,
        style_block: str | None = None,
        cover_styled: bool = False,
    ) -> list[Path | None]:
        """Generate one image per prompt. Returns paths (or None per
        failed slot). Slot 0 is treated as the cover (same convention
        as chatgpt_image_batch's prompt list ordering).
        """
        _ = topic  # noqa — kept for signature parity
        if not prompts:
            return []
        if out_paths is None or len(out_paths) != len(prompts):
            raise ValueError(
                "gemini: out_paths must be provided with same length as prompts",
            )

        results: list[Path | None] = []
        try:
            self._start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("gemini: session start failed: %s", exc)
            return [None] * len(prompts)

        cleanup = _is_cleanup_enabled()
        try:
            for idx, (raw_prompt, dest) in enumerate(zip(prompts, out_paths)):
                effective = _flatten(self._compose_prompt(
                    raw_prompt,
                    is_cover=(idx == 0),
                    size=size,
                    style_block=style_block,
                    cover_styled=cover_styled,
                ))
                logger.info(
                    "gemini: image %d/%d (cover=%s, prompt=%d chars, out=%s)",
                    idx + 1, len(prompts), idx == 0, len(effective), dest.name,
                )
                slot_ok = False
                try:
                    temp_chat = self._navigate_fresh_chat()
                    if not self._send_prompt(effective):
                        results.append(None)
                        continue
                    blob_url = self._wait_for_image()
                    if not blob_url:
                        logger.warning(
                            "gemini: image %d timed out (%ds)",
                            idx + 1, _GEN_TIMEOUT_SECONDS,
                        )
                        results.append(None)
                        continue
                    png = self._extract_png(blob_url)
                    if not png:
                        results.append(None)
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(png)
                    size_bytes = dest.stat().st_size
                    if size_bytes < _MIN_VALID_IMAGE_BYTES:
                        logger.warning(
                            "gemini: image %d too small (%d bytes) — discarding",
                            idx + 1, size_bytes,
                        )
                        dest.unlink(missing_ok=True)
                        results.append(None)
                        continue
                    logger.info(
                        "gemini: image %d OK — %d bytes -> %s",
                        idx + 1, size_bytes, dest,
                    )
                    slot_ok = True
                    results.append(dest)
                    # Temp chats are never saved — deletion only needed
                    # when we fell back to a normal (persisted) chat.
                    if cleanup and not temp_chat:
                        self._cleanup_current_chat()
                except PlaywrightTimeoutError as exc:
                    logger.warning("gemini: image %d timeout: %s", idx + 1, exc)
                    results.append(None)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("gemini: image %d error: %s", idx + 1, exc)
                    results.append(None)
                if not slot_ok:
                    # Small backoff so we don't stampede after an error
                    # (Gemini rate-limits soft-fail with 5-10s cooldown).
                    time.sleep(3)
        finally:
            self.close()

        return results
