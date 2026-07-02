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

Public API mirrors ChatGPTImageGenerator so chatgpt_batch_helper.py can
just swap backends behind USE_GEMINI_IMAGES.
"""
from __future__ import annotations

import base64
import logging
import os
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
        self._page = self._context.new_page()

    def close(self) -> None:
        for attr in ("_page", "_context", "_browser"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            try:
                obj.close()
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
    # Per-image flow
    # ------------------------------------------------------------------
    def _navigate_fresh_chat(self) -> None:
        """Open a brand-new tab for every image so Gemini's SPA state
        doesn't carry over between prompts.

        2026-07-02 dry-run showed that same-page ``goto(/app)`` between
        prompts leaves image-gen routing off for the 2nd+ prompt (only
        image #1 succeeded, #2 and #3 stayed in text mode and timed
        out). A fresh tab (new Page) fully resets SPA state and image
        routing re-engages on the ``画像を生成してください:`` trigger."""
        assert self._context is not None
        # Close prior page if any — keeps Chrome resource footprint down
        # across a 5-image batch.
        prior = self._page
        if prior is not None:
            try:
                prior.close()
            except Exception:  # noqa: BLE001
                pass
        self._page = self._context.new_page()
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

    def _send_prompt(self, prompt: str) -> bool:
        """Fill the Gemini textarea and press Enter. Returns True on
        successful send."""
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
                    page.keyboard.type(prompt, delay=12)
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

    def _extract_png(self) -> bytes | None:
        """Read the generated image via canvas.toDataURL — bypasses
        fetch()'s CORS boundary against blob: URLs. Returns raw PNG
        bytes or None."""
        assert self._page is not None
        try:
            b64 = self._page.evaluate("""
                () => {
                  const img = Array.from(document.querySelectorAll('img'))
                    .find(i => i.src.startsWith('blob:') && i.naturalWidth >= 512);
                  if (!img) return null;
                  const c = document.createElement('canvas');
                  c.width = img.naturalWidth;
                  c.height = img.naturalHeight;
                  const g = c.getContext('2d');
                  g.drawImage(img, 0, 0);
                  const dataUrl = c.toDataURL('image/png');
                  return dataUrl.split(',')[1] || null;
                }
            """)
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
        failed slot).

        - ``size``: accepted for interface parity; Gemini doesn't take
          size directives so we bake orientation into the prompt.
        - ``topic`` / ``style_block`` / ``cover_styled``: same. We
          concatenate the style_block into each prompt when given, since
          Gemini otherwise defaults to a generic aesthetic.
        """
        _ = size, topic  # noqa — kept for signature parity
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

        try:
            for idx, (raw_prompt, dest) in enumerate(zip(prompts, out_paths)):
                # Build the effective prompt: mandatory 「画像を生成して
                # ください:」 trigger + optional style block + user prompt.
                # Whether or not this is the cover, the trigger phrase is
                # what flips Gemini into the image-gen path (verified
                # 2026-07-02 PoC — English-only prompts stayed in text
                # mode and produced no image).
                parts = ["画像を生成してください:"]
                if style_block:
                    is_cover = idx == 0
                    if is_cover and not cover_styled:
                        # Cover intentionally NOT styled by the preset —
                        # this is the "infographic banner" default from
                        # ChatGPT flow. Skip style_block here.
                        pass
                    else:
                        parts.append(style_block.strip())
                parts.append(raw_prompt.strip())
                effective = "\n".join(p for p in parts if p)

                logger.info(
                    "gemini: image %d/%d (out=%s)",
                    idx + 1, len(prompts), dest.name,
                )
                slot_ok = False
                try:
                    self._navigate_fresh_chat()
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
                    png = self._extract_png()
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
