"""note.com article publisher using Playwright browser automation.

Automates the note.com editor to create and publish articles, with
support for paid article pricing tiers based on A/B/C quality grades.

Login state is persisted via a Playwright user data directory located at
``data/note-profile``. Run ``scripts/note_login.py`` once to authenticate.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Final

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# NOTE: NoteContentConverter was imported for generate-time
# mermaid→PNG conversion, but the publish pipeline now uses
# `_mermaid_to_ascii` inline and never instantiates the converter.
# Keeping the import caused a spurious dependency surface.

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_PROFILE_DIR: Final[Path] = _REPO_ROOT / "data" / "note-profile"

_NOTE_EDITOR_URL: Final[str] = "https://note.com/notes/new"
_NOTE_HOME_URL: Final[str] = "https://note.com/"

_NAV_TIMEOUT_MS: Final[int] = 45_000
_ELEMENT_TIMEOUT_MS: Final[int] = 20_000
_PUBLISH_TIMEOUT_MS: Final[int] = 60_000

# Matches local image paths such as ![](data/images/xxx.png) or
# ![alt](./data/images/xxx.png), with an optional ``"remote_url"``
# title attribute that survives to the publish step so the local
# path can be swapped for the CDN-hosted original.
_LOCAL_IMAGE_RE: Final[re.Pattern[str]] = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*\.?/?(?P<path>(?:data|docs)/images/[^)\s\"]+?\.(?:png|jpg|jpeg|gif|svg))(?:\s+\"(?P<title>[^\"]*)\")?\s*\)",
    re.IGNORECASE,
)


class NotePublisher:
    """Publish articles to note.com using Playwright with a persistent profile.

    The publisher expects that ``scripts/note_login.py`` has already been
    run once to authenticate and save cookies into ``data/note-profile``.

    Args:
        headless: Run Chromium in headless mode. Defaults to ``True``.
            Set to ``False`` to observe the browser for debugging.
    """

    def __init__(self, headless: bool = False) -> None:
        # NOTE: note.com's SPA does NOT render in headless mode as of 2026-04.
        # Default to headful; override only if you've verified it works.
        self._profile_dir: Path = _PROFILE_DIR
        self._headless: bool = headless
        self._playwright = None
        self._context: BrowserContext | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def publish_article(
        self,
        title: str,
        content: str,
        tags: list[str],
        price: int = 0,
        slug: str = "article",
        cover_image_path: str | None = None,
        inline_image_paths: list[str] | None = None,
    ) -> str:
        """Create and publish an article on note.com.

        Args:
            title: Article title.
            content: Article body (Markdown / plain text).
            tags: Tags to attach (up to 5 are used).
            price: Price in JPY; ``0`` publishes as free.
            slug: Slug used for naming converter-generated images.

        Returns:
            URL of the published article.

        Raises:
            RuntimeError: On login/captcha or publish failures.
        """
        # Convert mermaid → ASCII flowchart (note doesn't render mermaid)
        content = self._mermaid_to_ascii(content)

        # Image handling branch:
        #   • If the caller supplied inline_image_paths, note.com will
        #     host those for us via `_inject_inline_images`. In that case
        #     we must DROP every ![alt](data/images/... "url") reference
        #     from the body — note's ProseMirror refuses to render
        #     external <img src=...> tags and shows the raw Markdown
        #     as literal text otherwise (observed 2026-04-18: live
        #     article displayed `![photo of three women...](https://
        #     images.unsplash.com/...)` as visible text).
        #   • Without inline uploads we fall back to the previous
        #     behaviour of rewriting local paths to their remote CDN
        #     URL, which at least lets note render hotlinked images in
        #     the rare clients that accept them.
        if inline_image_paths:
            content = self._drop_local_images(content)
        else:
            content = self._strip_local_images(content)

        # Render to HTML — note's ProseMirror parses pasted HTML and
        # produces real headings, lists, anchors, and inline images.
        # We deliberately do NOT route through _markdown_to_plain in
        # this path because it flattens link/image syntax into
        # ``label (url)`` form, which is exactly what we are trying
        # to avoid.
        html = self._markdown_to_html_for_note(content)

        self._ensure_started()
        assert self._page is not None

        try:
            self._assert_logged_in()
            self._navigate_to_editor()
            self._input_title(title)
            if cover_image_path:
                # Don't silently publish a wrong-or-missing eyecatch.
                # The 16-article cross-contamination incident on
                # 2026-04-30 happened because this return value was
                # ignored: prior article's cover was still in the
                # editor, _set_eyecatch_on_current_page early-returned,
                # and the new post inherited the wrong thumbnail.
                ok = self._set_eyecatch_on_current_page(cover_image_path)
                if not ok:
                    raise RuntimeError(
                        f"eyecatch upload failed for {cover_image_path!r}; "
                        "refusing to publish without a verified cover",
                    )
            self._input_content_html(html)
            if inline_image_paths:
                self._inject_inline_images(inline_image_paths)
            self._open_publish_settings()
            self._input_tags(tags)
            if price > 0:
                self._set_price(price)
            url = self._click_publish()
            logger.info("Article published: %s", url)
            return url
        except PlaywrightTimeoutError as exc:
            logger.exception("Playwright timeout during publish: %s", title)
            raise RuntimeError(f"note公開に失敗しました (timeout): {exc}") from exc
        except PlaywrightError as exc:
            logger.exception("Playwright error during publish: %s", title)
            raise RuntimeError(f"note公開に失敗しました: {exc}") from exc

    @staticmethod
    def determine_price(overall_grade: str, evidence_level: str) -> int:
        """Calculate the article price from quality grades.

        Pricing tiers (by overall_grade + evidence_level):
          A + A evidence: 1,980 yen (premium)
          A + B evidence: 980 yen
          B + A evidence: 500 yen
          B + B evidence: 300 yen
          Otherwise: free
        """
        if overall_grade == "A" and evidence_level == "A":
            return 1980
        if overall_grade == "A":
            return 980
        if overall_grade == "B" and evidence_level == "A":
            return 500
        if overall_grade == "B":
            return 300
        return 0

    def close(self) -> None:
        """Close the Playwright browser context and release resources."""
        try:
            if self._context is not None:
                self._context.close()
                logger.info("Playwright context closed")
        except PlaywrightError:
            logger.warning("Browser context was already closed")
        finally:
            self._context = None
            self._page = None
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None

    def __enter__(self) -> "NotePublisher":
        self._ensure_started()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Private helpers — lifecycle
    # ------------------------------------------------------------------

    def _ensure_started(self) -> None:
        """Lazily start Playwright and open the persistent browser context."""
        if self._context is not None and self._page is not None:
            return
        if not self._profile_dir.exists():
            raise RuntimeError(
                "note.comログインが必要です。"
                "python scripts/note_login.py を実行してください"
            )
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            channel="msedge",
            headless=self._headless,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
            ],
        )
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        # Grant clipboard read/write at every note.com origin the
        # editor uses (editor.note.com for new + edit pages, plain
        # note.com for the legacy fallback). Without this the HTML
        # clipboard paste path silently degrades to keyboard.type and
        # external <img> elements never reach ProseMirror.
        for _origin in (
            "https://editor.note.com",
            "https://note.com",
        ):
            try:
                self._context.grant_permissions(
                    ["clipboard-read", "clipboard-write"],
                    origin=_origin,
                )
            except Exception as exc:
                logger.debug("clipboard permission grant skipped (%s): %s", _origin, exc)
        self._context.set_default_timeout(_ELEMENT_TIMEOUT_MS)
        self._context.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )
        logger.info("NotePublisher initialised (headless=%s)", self._headless)

    # ------------------------------------------------------------------
    # Private helpers — login & navigation
    # ------------------------------------------------------------------

    def _assert_logged_in(self) -> None:
        """Verify the persistent session is still logged in to note.com."""
        assert self._page is not None
        page = self._page
        page.goto(_NOTE_HOME_URL, wait_until="domcontentloaded")

        # If we got redirected to login, session is dead.
        if "/login" in page.url:
            raise RuntimeError(
                "note.comログインが必要です。"
                "python scripts/note_login.py を実行してください"
            )

        # Look for markers of a logged-in user: the 投稿 button or a
        # user/avatar menu. Any of these is sufficient.
        logged_in_selectors = [
            "a[href*='/notes/new']",
            "text=投稿",
            "text=記事投稿",
            "[data-testid='user-menu']",
            "button[aria-label*='メニュー']",
        ]
        for selector in logged_in_selectors:
            try:
                if page.locator(selector).first.is_visible(timeout=2_000):
                    return
            except PlaywrightError:
                continue

        # As a last check, try going to the editor directly; if we're
        # bounced to /login, the session is not valid.
        page.goto(_NOTE_EDITOR_URL, wait_until="domcontentloaded")
        if "/login" in page.url:
            raise RuntimeError(
                "note.comログインが必要です。"
                "python scripts/note_login.py を実行してください"
            )

    def _navigate_to_editor(self) -> None:
        """Open the new-article editor and wait for it to be ready."""
        assert self._page is not None
        page = self._page

        # note editor moved to editor.note.com/new (as of 2026)
        target_urls = [
            "https://editor.note.com/new",
            "https://note.com/notes/new",
        ]

        loaded = False
        last_error = None
        for target in target_urls:
            try:
                page.goto(target, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
                page.wait_for_timeout(3000)  # Give SPA time to render

                if "login" in page.url or "enter" in page.url:
                    raise RuntimeError(
                        "noteログインが必要です。scripts/note_login.py を実行してください"
                    )

                if "captcha" in page.url.lower():
                    raise RuntimeError("note.comでCAPTCHAが表示されました")

                # Try to find editor elements with longer wait
                try:
                    page.wait_for_selector(
                        "input[placeholder*='タイトル'], "
                        "textarea[placeholder*='タイトル'], "
                        ".ProseMirror, [contenteditable='true']",
                        timeout=15_000,
                    )
                    loaded = True
                    break
                except PlaywrightTimeoutError:
                    last_error = f"Editor not ready at {target}"
                    continue
            except PlaywrightError as e:
                last_error = str(e)
                continue

        if not loaded:
            # Save debug screenshot
            try:
                (_REPO_ROOT / "logs").mkdir(exist_ok=True)
                page.screenshot(
                    path=str(_REPO_ROOT / "logs" / "note_nav_failed.png"),
                    full_page=True,
                )
            except Exception:
                pass
            raise RuntimeError(
                f"noteエディタを開けませんでした: {last_error}. "
                f"URL: {page.url}"
            )

    # ------------------------------------------------------------------
    # Private helpers — editor input
    # ------------------------------------------------------------------

    def _input_title(self, title: str) -> None:
        """Focus the title field and type the article title."""
        assert self._page is not None
        page = self._page
        title_selectors = [
            "textarea[placeholder*='タイトル']",
            "input[placeholder*='タイトル']",
            "[data-testid='editor-title']",
        ]
        for selector in title_selectors:
            loc = page.locator(selector).first
            try:
                loc.wait_for(state="visible", timeout=5_000)
            except PlaywrightTimeoutError:
                continue
            loc.click()
            loc.fill("")
            loc.type(title, delay=10)
            return
        raise RuntimeError("タイトル入力欄が見つかりません")

    def _input_content(self, content: str) -> None:
        """Focus the body editor and type the article content."""
        assert self._page is not None
        page = self._page
        body_selectors = [
            ".ProseMirror",
            "[contenteditable='true']",
            "[data-testid='note-body']",
        ]
        for selector in body_selectors:
            loc = page.locator(selector).first
            try:
                loc.wait_for(state="visible", timeout=5_000)
            except PlaywrightTimeoutError:
                continue
            loc.click()
            # Use keyboard.type so newlines produce real paragraph breaks.
            page.keyboard.type(content, delay=2)
            return
        raise RuntimeError("本文エディタが見つかりません")

    def _input_content_html(self, html: str) -> None:
        """Focus the body editor and paste *html* via the clipboard.

        Used by both publish and edit flows so headings, lists,
        anchors and inline images all land as proper ProseMirror
        nodes instead of plain text.
        """
        assert self._page is not None
        page = self._page
        body = page.locator(".ProseMirror").first
        body.wait_for(state="visible", timeout=5_000)
        body.click()
        page.wait_for_timeout(400)
        # Editor is empty on a fresh draft, but we still issue
        # Ctrl+A/Delete to be safe (idempotent).
        page.keyboard.press("Control+a")
        page.wait_for_timeout(150)
        page.keyboard.press("Delete")
        page.wait_for_timeout(150)
        self._paste_html(page, html)
        page.wait_for_timeout(1000)
        logger.info("Body input via HTML clipboard paste")

    @staticmethod
    def _mermaid_to_ascii(content: str) -> str:
        """Convert mermaid code blocks to plain-text arrow flow diagrams.

        note.com doesn't render mermaid, and inline images are unreliable.
        Convert to simple `A → B → C` arrow notation inside code blocks
        (which note renders as monospace, preserving alignment).
        """
        mermaid_re = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)

        def replace(match):
            mermaid_src = match.group(1).strip()
            lines = []
            # Extract simple node names from common mermaid patterns
            # Matches: A[Label] --> B[Label]  or  A --> B
            edge_re = re.compile(
                r"(\w+)(?:\[([^\]]+)\])?\s*-->\s*(\w+)(?:\[([^\]]+)\])?"
            )
            edges = edge_re.findall(mermaid_src)
            if not edges:
                return "```\n" + mermaid_src + "\n```"

            # Build a sequence: node → node → node
            seen_nodes = []
            for src, src_label, dst, dst_label in edges:
                src_name = src_label or src
                dst_name = dst_label or dst
                if not seen_nodes:
                    seen_nodes.append(src_name)
                seen_nodes.append(dst_name)

            # Format as a clean monospace arrow chain
            # Wrap long chains: max 40 chars per line
            chain = " → ".join(seen_nodes)
            if len(chain) <= 60:
                return "```\n" + chain + "\n```"

            # Multi-line vertical flow
            lines = []
            for i, node in enumerate(seen_nodes):
                lines.append(f"  [{node}]")
                if i < len(seen_nodes) - 1:
                    lines.append("    │")
                    lines.append("    ▼")
            return "```\n" + "\n".join(lines) + "\n```"

        return mermaid_re.sub(replace, content)

    @staticmethod
    def _extract_local_images(content: str) -> list[tuple[str, str]]:
        """Extract (match_str, file_path) tuples for local images."""
        results = []
        for m in _LOCAL_IMAGE_RE.finditer(content):
            full_match = m.group(0)
            file_path = m.group(1)
            abs_path = _REPO_ROOT / file_path
            if abs_path.exists():
                results.append((full_match, str(abs_path)))
        return results

    def _input_content_with_images(
        self, content: str, image_paths: list[tuple[str, str]]
    ) -> None:
        """Input content and upload local images inline at their positions."""
        assert self._page is not None
        page = self._page

        # If no images, fall back to simple text input
        if not image_paths:
            self._input_content(content)
            return

        # Split content by image references, type text between, upload images
        body_selectors = [".ProseMirror", "[contenteditable='true']"]
        editor = None
        for selector in body_selectors:
            loc = page.locator(selector).first
            try:
                loc.wait_for(state="visible", timeout=5_000)
                editor = loc
                break
            except PlaywrightTimeoutError:
                continue
        if editor is None:
            raise RuntimeError("本文エディタが見つかりません")

        editor.click()

        # Build a list of segments: text, image, text, image, ...
        remaining = content
        for match_str, abs_path in image_paths:
            idx = remaining.find(match_str)
            if idx == -1:
                continue
            before = remaining[:idx]
            remaining = remaining[idx + len(match_str):]

            # Type text before image
            if before:
                page.keyboard.type(before, delay=1)

            # Upload image via file input (note editor uses a hidden file input)
            try:
                self._upload_image(abs_path)
                logger.info("Uploaded image: %s", abs_path)
            except Exception as e:
                logger.warning("Image upload failed for %s: %s", abs_path, e)
                # Continue without the image
                page.keyboard.type(f"[画像: {Path(abs_path).name}]", delay=1)

        # Type remaining text
        if remaining:
            page.keyboard.type(remaining, delay=1)

    def _upload_image(self, file_path: str) -> None:
        """Upload an image to note.com editor via paste from clipboard.

        Uses ProseMirror's native paste image handling — bypasses note's
        custom add-block menu and CropModal entirely.
        """
        assert self._page is not None
        page = self._page

        # Read image as base64
        import base64
        from pathlib import Path as _P
        img_bytes = _P(file_path).read_bytes()
        b64 = base64.b64encode(img_bytes).decode()
        mime = "image/png" if file_path.endswith(".png") else "image/jpeg"

        # Inject image into clipboard via DataTransfer + dispatch paste event
        page.evaluate(
            """({b64, mime}) => {
                const byteString = atob(b64);
                const ab = new ArrayBuffer(byteString.length);
                const ia = new Uint8Array(ab);
                for (let i = 0; i < byteString.length; i++) {
                    ia[i] = byteString.charCodeAt(i);
                }
                const blob = new Blob([ab], {type: mime});
                const file = new File([blob], 'image.png', {type: mime});
                const dt = new DataTransfer();
                dt.items.add(file);
                const editor = document.querySelector('.ProseMirror, [contenteditable="true"]');
                if (editor) {
                    editor.focus();
                    const event = new ClipboardEvent('paste', {
                        clipboardData: dt,
                        bubbles: true,
                        cancelable: true,
                    });
                    Object.defineProperty(event, 'clipboardData', {value: dt});
                    editor.dispatchEvent(event);
                }
            }""",
            {"b64": b64, "mime": mime},
        )

        # Wait for upload to complete and any modal to appear/disappear
        page.wait_for_timeout(3000)
        self._dismiss_crop_modal()
        page.wait_for_timeout(1500)

    def _dismiss_personal_info_modal(self) -> None:
        """Close the 本人情報の登録 modal if it appears (paid article requirement)."""
        assert self._page is not None
        page = self._page

        # Look for the personal info modal
        modal_texts = ["本人情報の入力", "本人情報の登録"]
        modal_found = False
        for text in modal_texts:
            try:
                if page.locator(f":text('{text}')").first.is_visible(timeout=800):
                    modal_found = True
                    logger.info("Personal info modal detected")
                    break
            except Exception:
                continue

        if not modal_found:
            return

        # Close via X button, or キャンセル, or click outside
        close_selectors = [
            "button:has-text('キャンセル')",
            "button[aria-label='閉じる']",
            "button[aria-label='Close']",
            "button:has-text('×')",
            "[role='dialog'] button:first-child",
        ]
        for sel in close_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=2000)
                    page.wait_for_timeout(800)
                    logger.info("Closed personal info modal via: %s", sel)
                    return
            except Exception:
                continue

        # Last resort: press Escape
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        logger.warning("Used Escape to dismiss personal info modal")

    def _dismiss_crop_modal(self) -> None:
        """Close the image crop modal by clicking 保存/完了/適用."""
        assert self._page is not None
        page = self._page

        # Check if crop modal is visible
        crop_modal = page.locator(".CropModal__overlay, [class*='CropModal']").first
        try:
            if not crop_modal.is_visible(timeout=500):
                return
        except Exception:
            return

        logger.info("Crop modal detected, dismissing...")

        confirm_selectors = [
            "button:has-text('保存')",
            "button:has-text('完了')",
            "button:has-text('適用')",
            "button:has-text('OK')",
            "button:has-text('決定')",
            "[class*='CropModal'] button[type='submit']",
            "[class*='CropModal'] button:last-child",
        ]

        for selector in confirm_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    # Verify modal closed
                    if not crop_modal.is_visible(timeout=500):
                        logger.info("Crop modal closed via: %s", selector)
                        return
            except Exception:
                continue

        logger.warning("Could not dismiss crop modal; pressing Escape")
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

    def _open_publish_settings(self) -> None:
        """Click the 公開設定 button to open the publishing sidebar."""
        assert self._page is not None
        page = self._page
        candidates = [
            "button:has-text('公開設定')",
            "button:has-text('公開に進む')",
            "[data-testid='publish-settings']",
        ]
        for selector in candidates:
            loc = page.locator(selector).first
            try:
                loc.wait_for(state="visible", timeout=5_000)
            except PlaywrightTimeoutError:
                continue
            loc.click()
            return
        logger.warning("公開設定ボタンが見つかりません (新UIの可能性)")

    def _input_tags(self, tags: list[str]) -> None:
        """Enter up to five tags via the tag input field."""
        if not tags:
            return
        assert self._page is not None
        page = self._page
        tag_selectors = [
            "input[placeholder*='ハッシュタグ']",
            "input[placeholder*='タグ']",
            "[data-testid='tag-input']",
        ]
        tag_input = None
        for selector in tag_selectors:
            loc = page.locator(selector).first
            try:
                loc.wait_for(state="visible", timeout=5_000)
                tag_input = loc
                break
            except PlaywrightTimeoutError:
                continue
        if tag_input is None:
            logger.warning("タグ入力欄が見つかりません。タグ追加をスキップします")
            return
        for tag in tags[:5]:
            try:
                tag_input.click()
                tag_input.type(tag, delay=10)
                page.keyboard.press("Enter")
                page.wait_for_timeout(300)
            except PlaywrightError as exc:
                logger.warning("タグ '%s' の追加に失敗: %s", tag, exc)

    def _set_price(self, price: int) -> None:
        """Enable paid-article mode and set the price."""
        assert self._page is not None
        page = self._page
        try:
            paid_toggle = page.locator(
                "text=有料"
            ).first
            paid_toggle.wait_for(state="visible", timeout=5_000)
            paid_toggle.click()

            price_input = page.locator(
                "input[type='number'], [data-testid='price-input']"
            ).first
            price_input.wait_for(state="visible", timeout=5_000)
            price_input.fill(str(price))
            logger.debug("Price set to %d yen", price)
        except PlaywrightTimeoutError:
            logger.warning("価格設定UIが見つかりません。無料で公開します")
        except PlaywrightError as exc:
            logger.warning("価格設定に失敗: %s。無料で公開します", exc)

    def _click_publish(self) -> str:
        """Click the publish button and return the resulting article URL."""
        assert self._page is not None
        page = self._page

        # Dismiss "本人情報の登録" modal if present (only required for paid articles)
        self._dismiss_personal_info_modal()

        # On the publish settings page, look for the final publish button
        page.wait_for_timeout(1500)

        publish_selectors = [
            "button:has-text('投稿する')",
            "button:has-text('投稿')",
            "button:has-text('公開する')",
            "button:has-text('公開')",
            "button:has-text('有料販売する')",
            "[data-testid='publish-button']",
            "button[class*='publish']",
        ]

        # Try clicking the first visible publish button
        clicked = False
        for selector in publish_selectors:
            try:
                locs = page.locator(selector).all()
                for loc in locs:
                    try:
                        if loc.is_visible(timeout=500):
                            loc.scroll_into_view_if_needed(timeout=2000)
                            loc.click(timeout=3000)
                            clicked = True
                            logger.info("Publish clicked via: %s", selector)
                            break
                    except Exception:
                        continue
                if clicked:
                    break
            except Exception:
                continue

        if not clicked:
            # Last resort: screenshot for debugging
            try:
                page.screenshot(path="logs/publish_failed.png", full_page=True)
                logger.error("Screenshot saved to logs/publish_failed.png")
            except Exception:
                pass
            raise RuntimeError("投稿ボタンが見つかりません")

        # Wait for /publish/ page to load
        page.wait_for_timeout(3000)

        # On /publish/ page, click the FINAL publish button
        # This is usually a different button - look for ones in the publish settings sidebar
        logger.info("On /publish/ page, looking for final publish button...")
        final_publish_clicked = False
        final_selectors = [
            "button:has-text('公開する'):not(:has-text('予約'))",
            "button:has-text('投稿する'):not(:has-text('予約'))",
            "button[type='submit']:has-text('公開')",
            "button[type='submit']:has-text('投稿')",
        ]
        for selector in final_selectors:
            try:
                btns = page.locator(selector).all()
                # Pick the last visible one (usually the actual submit button)
                for btn in reversed(btns):
                    try:
                        if btn.is_visible(timeout=500):
                            btn.scroll_into_view_if_needed(timeout=2000)
                            btn.click(timeout=3000)
                            final_publish_clicked = True
                            logger.info("Final publish clicked: %s", selector)
                            break
                    except Exception:
                        continue
                if final_publish_clicked:
                    break
            except Exception:
                continue

        # Wait for navigation to the published article page (URL contains /n/)
        # OR for a popup to appear
        try:
            page.wait_for_url("**/n/**", timeout=30_000)
            logger.info("Article published, URL: %s", page.url)
        except PlaywrightTimeoutError:
            logger.info("No URL change yet, checking for post-publish popup")

        # Close any post-publish popup (continuous-posting warning, etc.)
        self._dismiss_popups()

        # Wait once more for URL change after popup dismissal
        try:
            if "/n/" not in page.url:
                page.wait_for_url("**/n/**", timeout=15_000)
        except PlaywrightTimeoutError:
            logger.warning(
                "公開後のリダイレクトを検出できませんでした。現在のURL: %s", page.url
            )

        return page.url

    def _dismiss_popups(self) -> None:
        """Close post-publish popups / modals that note shows."""
        assert self._page is not None
        page = self._page
        page.wait_for_timeout(1500)

        dismiss_selectors = [
            "button[aria-label='閉じる']",
            "button[aria-label='Close']",
            "button[aria-label='close']",
            "[role='dialog'] button[aria-label*='close' i]",
            "[role='dialog'] button[aria-label*='閉じる']",
            "button:has-text('×')",
            "button:has-text('✕')",
            "button:has-text('閉じる')",
            "button:has-text('あとで')",
            "button:has-text('キャンセル')",
            "button:has-text('OK')",
            "[data-testid='modal-close']",
            # Top-right X button in modal (usually first button in dialog)
            "[role='dialog'] button:first-child",
        ]
        for _ in range(3):  # Multiple popups may stack
            closed_any = False
            for selector in dismiss_selectors:
                try:
                    loc = page.locator(selector).first
                    if loc.is_visible(timeout=500):
                        loc.click(timeout=2000)
                        page.wait_for_timeout(500)
                        closed_any = True
                except Exception:
                    continue
            if not closed_any:
                break

    # ------------------------------------------------------------------
    # Private helpers — content preprocessing
    # ------------------------------------------------------------------

    def edit_article(
        self,
        url: str,
        new_title: str | None = None,
        new_content: str | None = None,
        inline_image_paths: list[str] | None = None,
        cover_image_path: str | None = None,
    ) -> bool:
        """Edit an existing note article (preserves URL and impressions).

        Args:
            url: Full note URL (https://note.com/user/n/xxxxx)
            new_title: New title (None = keep existing)
            new_content: New body content (None = keep existing)
            inline_image_paths: Optional list of local image files to
                upload inline at the top of the body via note's
                native ProseMirror paste-image handler. Each file is
                uploaded after the body paste finishes and before the
                publish/update click. note then re-hosts the image
                under assets.st-note.com.

        Returns:
            True on success
        """
        self._ensure_started()
        assert self._page is not None
        page = self._page

        try:
            self._assert_logged_in()

            import re as _re
            m = _re.search(r"/n/([a-zA-Z0-9]+)", url)
            if not m:
                logger.error("Invalid note URL: %s", url)
                return False
            note_id = m.group(1)

            # Navigate to edit page
            edit_url = f"https://editor.note.com/notes/{note_id}/edit/"
            page.goto(edit_url, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
            page.wait_for_timeout(5000)

            if "login" in page.url or "enter" in page.url:
                raise RuntimeError("note.comログインが必要です")

            # Wait for editor
            try:
                page.wait_for_selector(".ProseMirror", timeout=20000)
            except PlaywrightTimeoutError:
                logger.error("エディタ読み込みタイムアウト")
                return False

            # Update title if provided
            if new_title:
                title_selectors = [
                    "textarea[placeholder*='タイトル']",
                    "input[placeholder*='タイトル']",
                    "[data-testid='editor-title']",
                ]
                title_updated = False
                for sel in title_selectors:
                    try:
                        loc = page.locator(sel).first
                        if loc.is_visible(timeout=2000):
                            loc.click()
                            # Select all and delete
                            page.keyboard.press("Control+a")
                            page.wait_for_timeout(200)
                            page.keyboard.press("Delete")
                            page.wait_for_timeout(200)
                            loc.type(new_title, delay=10)
                            title_updated = True
                            logger.info("Title updated via %s", sel)
                            break
                    except Exception:
                        continue
                if not title_updated:
                    logger.warning("タイトル更新スキップ")

            # Update body if provided
            if new_content:
                # Convert markdown to HTML and paste via clipboard so
                # note's ProseMirror editor parses real <a> elements.
                # The Ctrl+K dialog flow is too flaky across multiple
                # links — ProseMirror keeps absorbing subsequent text
                # into the previous link mark regardless of how we
                # try to exit it. HTML-clipboard paste bypasses the
                # mark-exit problem entirely.
                new_content = self._mermaid_to_ascii(new_content)
                if inline_image_paths:
                    new_content = self._drop_local_images(new_content)
                else:
                    new_content = self._strip_local_images(new_content)
                html = self._markdown_to_html_for_note(new_content)

                body = page.locator(".ProseMirror").first
                body.click()
                page.wait_for_timeout(500)
                page.keyboard.press("Control+a")
                page.wait_for_timeout(300)
                page.keyboard.press("Delete")
                page.wait_for_timeout(500)
                self._paste_html(page, html)
                page.wait_for_timeout(1200)
                logger.info("Body updated via HTML clipboard paste")

            # Upload inline images via the shared helper.
            if inline_image_paths:
                self._inject_inline_images(inline_image_paths)

            # Cover image (eyecatch) upload via shared helper. This is
            # the edit path — we always want to replace an existing
            # cover, not skip the upload just because one is present.
            if cover_image_path:
                ok = self._set_eyecatch_on_current_page(
                    cover_image_path, force_replace=True,
                )
                if not ok:
                    logger.error(
                        "edit_article: eyecatch swap failed for %r; "
                        "aborting save to avoid leaving the old cover.",
                        cover_image_path,
                    )
                    return False
                # ChatGPT-generated PNGs run 1.5-3 MB. note's eyecatch
                # uploader takes 5-15s to ingest+resize them, during
                # which 公開に進む is disabled. Without this poll the
                # next step click() is a no-op and the article saves
                # with the old cover. Wait for the eyecatch <img> to
                # have a real https src (not the local blob/data URI)
                # before proceeding — that signals the upload finished.
                upload_deadline = time.time() + 30
                while time.time() < upload_deadline:
                    try:
                        ready = page.evaluate(
                            """() => {
                                const img = document.querySelector('img[alt="eyecatch"]');
                                if (!img || !img.src) return false;
                                return img.src.startsWith('https://');
                            }"""
                        )
                    except Exception:
                        ready = False
                    if ready:
                        break
                    page.wait_for_timeout(500)

            # Click 公開に進む / 更新する button
            page.wait_for_timeout(1500)
            proceed_selectors = [
                "button:has-text('公開に進む')",
                "button:has-text('更新')",
                "button:has-text('公開設定')",
            ]
            for sel in proceed_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click(timeout=3000)
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    continue

            # Dismiss personal info modal if any
            self._dismiss_personal_info_modal()
            page.wait_for_timeout(1500)

            # Click final update button
            update_selectors = [
                "button:has-text('更新する')",
                "button:has-text('公開する'):not(:has-text('予約'))",
                "button:has-text('投稿する'):not(:has-text('予約'))",
            ]
            updated = False
            for sel in update_selectors:
                try:
                    btns = page.locator(sel).all()
                    for btn in reversed(btns):
                        try:
                            if btn.is_visible(timeout=500):
                                btn.scroll_into_view_if_needed(timeout=2000)
                                btn.click(timeout=3000)
                                updated = True
                                logger.info("Update clicked: %s", sel)
                                break
                        except Exception:
                            continue
                    if updated:
                        break
                except Exception:
                    continue

            if not updated:
                logger.error("更新ボタンが見つかりません")
                try:
                    page.screenshot(
                        path=str(_REPO_ROOT / "logs" / "note_edit_failed.png"),
                        full_page=True,
                    )
                except Exception:
                    pass
                return False

            page.wait_for_timeout(3000)
            self._dismiss_popups()
            logger.info("Article edited: %s", url)
            return True

        except Exception as e:
            logger.exception("記事編集失敗: %s", url)
            return False

    def delete_article(self, url: str) -> bool:
        """Delete a published note article via dashboard.

        Flow (verified 2026-04):
        1. Navigate to https://note.com/notes (dashboard)
        2. Find the article's card by matching note ID in its link
        3. Click the その他 button inside that specific card
        4. Click 削除 in the popup menu
        5. Confirm deletion

        Args:
            url: Full note article URL (https://note.com/xxx/n/yyyyy)

        Returns:
            True if deleted successfully
        """
        self._ensure_started()
        assert self._page is not None
        page = self._page

        try:
            self._assert_logged_in()

            import re as _re
            m = _re.search(r"/n/([a-zA-Z0-9]+)", url)
            if not m:
                logger.error("Invalid note URL: %s", url)
                return False
            note_id = m.group(1)

            # Navigate to dashboard
            page.goto("https://note.com/notes", wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
            page.wait_for_timeout(5000)

            # Find the card's "その他" button by looking up the DOM tree
            # from the link containing the note ID
            result = page.evaluate(
                """(noteId) => {
                    const links = Array.from(document.querySelectorAll('a[href*="' + noteId + '"]'));
                    if (!links.length) return 'NO_LINK';
                    let el = links[0];
                    while (el && el.parentElement) {
                        const btn = el.parentElement.querySelector('button[aria-label*="その他"]');
                        if (btn) {
                            btn.setAttribute('data-target-delete', '1');
                            return 'FOUND';
                        }
                        el = el.parentElement;
                    }
                    return 'NOT_FOUND';
                }""",
                note_id,
            )

            if result != "FOUND":
                logger.error("記事カードが見つかりません (id=%s, result=%s)", note_id, result)
                try:
                    page.screenshot(
                        path=str(_REPO_ROOT / "logs" / "note_delete_failed.png"),
                        full_page=True,
                    )
                except Exception:
                    pass
                return False

            # Click the card's その他 button
            menu_btn = page.locator("button[data-target-delete='1']").first
            menu_btn.click(timeout=3000)
            page.wait_for_timeout(1000)

            # Click 削除 button
            deleted_clicked = False
            delete_btns = page.locator("button:has-text('削除')").all()
            for btn in delete_btns:
                try:
                    if btn.is_visible(timeout=500):
                        text = btn.evaluate("el => el.textContent.trim()")
                        if text == "削除":
                            btn.click(timeout=2000)
                            deleted_clicked = True
                            logger.info("削除ボタンクリック成功")
                            break
                except Exception:
                    continue

            if not deleted_clicked:
                logger.error("削除ボタンが見つかりません")
                try:
                    page.screenshot(
                        path=str(_REPO_ROOT / "logs" / "note_delete_failed.png"),
                        full_page=True,
                    )
                except Exception:
                    pass
                return False

            # Confirm deletion
            page.wait_for_timeout(1000)
            confirm_clicked = False
            confirm_selectors = [
                "button:has-text('削除する')",
                "button:has-text('はい')",
                "button:has-text('OK')",
            ]
            for sel in confirm_selectors:
                try:
                    btn = page.locator(sel).last
                    if btn.is_visible(timeout=2000):
                        btn.click(timeout=2000)
                        confirm_clicked = True
                        break
                except Exception:
                    continue

            if not confirm_clicked:
                logger.error("削除確認ダイアログが押せませんでした")
                try:
                    page.screenshot(
                        path=str(_REPO_ROOT / "logs" / "note_delete_confirm_failed.png"),
                        full_page=True,
                    )
                except Exception:
                    pass
                return False

            page.wait_for_timeout(3000)

            # Verify: article URL should now return 404
            import requests as _requests
            try:
                resp = _requests.head(url, allow_redirects=True, timeout=10)
                if resp.status_code == 404:
                    logger.info("Article deleted and verified (404): %s", url)
                    return True
                logger.warning(
                    "Delete confirmed but URL still returns %d: %s",
                    resp.status_code, url,
                )
                return False
            except Exception as e:
                # Can't verify — assume success based on click
                logger.warning("Delete verification failed: %s", e)
                return True

        except Exception as e:
            logger.exception("記事削除失敗: %s", url)
            return False

    @staticmethod
    def _ascii_to_bold(text: str) -> str:
        """Convert ASCII letters/digits to Unicode sans-serif bold.

        Japanese characters are left unchanged (they don't have bold variants
        in Unicode that render consistently on note). ASCII becomes visually
        thicker.
        """
        result = []
        for c in text:
            code = ord(c)
            # Uppercase A-Z → 𝗔-𝗭 (Mathematical Sans-serif Bold Capital)
            if 0x41 <= code <= 0x5A:
                result.append(chr(0x1D5D4 + code - 0x41))
            # Lowercase a-z → 𝗮-𝘇
            elif 0x61 <= code <= 0x7A:
                result.append(chr(0x1D5EE + code - 0x61))
            # Digits 0-9 → 𝟬-𝟵
            elif 0x30 <= code <= 0x39:
                result.append(chr(0x1D7EC + code - 0x30))
            else:
                # Japanese/symbols: wrap in 『』 for emphasis (only if whole word is Japanese)
                result.append(c)
        converted = "".join(result)
        # If no ASCII was converted (pure Japanese), wrap in 『』 instead
        if converted == text and text.strip():
            return f"『{text}』"
        return converted

    @staticmethod
    def _strip_emojis(content: str) -> str:
        """Remove Unicode emojis but keep math bold chars + kaomoji.

        Carefully avoid stripping Mathematical Alphanumeric Symbols
        (U+1D400-U+1D7FF) used for visual bold.
        """
        # Specific emoji blocks only (do NOT include math bold range)
        emoji_pattern = re.compile(
            "["
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F680-\U0001F6FF"  # transport
            "\U0001F900-\U0001F9FF"  # supplemental symbols
            "\U0001FA00-\U0001FAFF"  # chess + symbols
            "\U00002702-\U000027B0"  # dingbats
            "]+",
            flags=re.UNICODE,
        )
        # Remove ZWJ sequences (used for composite emojis like 👩‍🦲)
        content = re.sub(r"\u200d", "", content)
        return emoji_pattern.sub("", content)

    # Markdown link pattern reused by _type_with_embedded_links so the
    # typing step recognises the same syntax _markdown_to_plain leaves
    # alone when ``preserve_links=True``.
    _INLINE_LINK_RE = re.compile(
        r"\[([^\]]+)\]\(((?:[^()]|\([^)]*\))+)\)"
    )

    @staticmethod
    def _type_with_embedded_links(page, content: str) -> None:
        """Type *content* into the current note editor focus.

        Plain-text chunks are typed verbatim. Each ``[anchor](url)``
        markdown link is materialised as an embedded note link by:

        1. Typing the anchor text.
        2. Selecting that text backwards via Shift+ArrowLeft.
        3. Pressing Ctrl+K to open note's link dialog.
        4. Pasting the URL from the clipboard (avoids any special-char
           issues with ``?``, ``&``, ``%``, etc. in Google Maps URLs).
        5. Pressing Enter to confirm the dialog.
        6. Pressing ArrowRight to step **out of** the newly-created
           link mark — without this ProseMirror keeps subsequent
           typed characters inside the link mark, so later paragraphs
           end up as part of the previous ``<a>`` element.

        This is the only way to produce a real embedded link via
        Playwright because note.com's ProseMirror editor does not
        parse markdown on input — it must be told via the editor's
        own affordances.
        """
        pos = 0
        for m in NotePublisher._INLINE_LINK_RE.finditer(content):
            before = content[pos : m.start()]
            if before:
                page.keyboard.type(before, delay=2)
            anchor = m.group(1)
            url = m.group(2).strip()

            # Type the anchor, then select it backwards.
            page.keyboard.type(anchor, delay=2)
            for _ in range(len(anchor)):
                page.keyboard.press("Shift+ArrowLeft")
            page.wait_for_timeout(150)

            # Open the link dialog.
            page.keyboard.press("Control+k")
            page.wait_for_timeout(400)

            # Paste the URL into the dialog's input field via the
            # clipboard, not keyboard.type — the latter garbles URLs
            # containing ``?``, ``&`` and URL-encoded bytes on some
            # OS keyboard layouts, which silently produces a
            # malformed href and drops the anchor.
            NotePublisher._paste_text(page, url)
            page.wait_for_timeout(200)
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)

            # Step out of the link mark so the next chunk lands as
            # plain text rather than being absorbed into the just-
            # created ``<a>`` element.
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(80)

            pos = m.end()

        tail = content[pos:]
        if tail:
            page.keyboard.type(tail, delay=2)

    def _inject_inline_images(self, image_paths: list[str]) -> None:
        """Upload each inline image in front of its own H2 section so the
        article reads as heading → hero image → prose, rather than one
        cluster of 4 images right at the top.

        The previous behaviour — parking the caret at ``blocks[1]`` and
        uploading every image there — produced a visual stack that the
        user flagged as "いたずらに連続に配置" and that drew attention
        to the tiny caption under each photo.

        Algorithm:
          1. Query ProseMirror for the current H2 block indices.
          2. Pick up to ``len(image_paths)`` H2 targets, evenly spaced,
             skipping the very first H2 when there are enough sections
             (keeps the intro paragraph image-free).
          3. Process from last target to first — each upload inserts
             extra blocks above the target H2, so reverse order keeps
             earlier indices valid. If that fails, re-query.
          4. Caption after each image is italicised + shortened to
             "※イメージ画像" so it stays subtle under the photo.
        """
        assert self._page is not None
        page = self._page
        if not image_paths:
            return

        body_loc = page.locator(".ProseMirror").first
        body_loc.click()
        page.wait_for_timeout(300)

        # --- Target selection ----------------------------------------
        h2_indices: list[int] = page.evaluate(
            """() => {
                const editor = document.querySelector('.ProseMirror');
                if (!editor) return [];
                const blocks = Array.from(editor.children);
                const out = [];
                blocks.forEach((b, i) => {
                    if (b && b.tagName === 'H2') out.push(i);
                });
                return out;
            }"""
        )

        n_imgs = len(image_paths)
        if h2_indices:
            # Skip the very first H2 when we have enough room so the
            # opening section stays clean.
            h2_pool = h2_indices[1:] if len(h2_indices) > n_imgs else h2_indices
            pool_size = len(h2_pool)
            target_block_idxs: list[int] = []
            for i in range(n_imgs):
                # Evenly spaced pick from the pool.
                idx = int(round(i * pool_size / max(n_imgs, 1)))
                idx = min(max(idx, 0), pool_size - 1)
                block_idx = h2_pool[idx]
                if block_idx in target_block_idxs:
                    # Avoid collisions when fewer H2s than images —
                    # push to the next unused slot.
                    for cand in h2_pool:
                        if cand not in target_block_idxs:
                            block_idx = cand
                            break
                target_block_idxs.append(block_idx)
        else:
            # No H2s found — fall back to the old behaviour so at
            # least the images land somewhere sensible.
            target_block_idxs = [1] * n_imgs

        logger.info(
            "Injecting %d inline image(s) across H2 blocks %s "
            "(of %d H2s total)",
            n_imgs, target_block_idxs, len(h2_indices),
        )

        # --- Upload in reverse so earlier indices stay valid ---------
        # Process from last H2 target to first: ProseMirror shifts
        # subsequent block indices downward by +1 or +2 per insertion,
        # but earlier indices never move, so iterating high→low keeps
        # the remaining targets stable even without re-querying.
        pairs = list(zip(image_paths, target_block_idxs))
        for path, block_idx in sorted(pairs, key=lambda kv: kv[1], reverse=True):
            try:
                # Target the *paragraph directly after* the H2 rather
                # than the H2 itself. ProseMirror's schema refuses
                # image figure nodes inside H2 elements, so placing
                # the caret at position 0 of the H2 made paste silently
                # drop the image and keep only the caption text —
                # which is exactly what the user just reported.
                placed = page.evaluate(
                    """(h2Idx) => {
                        const editor = document.querySelector('.ProseMirror');
                        if (!editor) return {ok: false, reason: 'no-editor'};
                        const blocks = Array.from(editor.children);
                        // Prefer the block after the H2 (the first
                        // paragraph of that section). Fall back to the
                        // H2 itself if there is no following block.
                        const after = blocks[h2Idx + 1];
                        const target = (after && after.tagName !== 'H2')
                            ? after
                            : (blocks[h2Idx] || blocks[blocks.length - 1]);
                        if (!target) return {ok: false, reason: 'no-target'};
                        // setStart at position 0 inside a paragraph
                        // node → caret at the very start of the text.
                        // Paste of an image file then causes ProseMirror
                        // to insert a figure block *above* the target
                        // block, so the image lands between the H2 and
                        // the body paragraph — exactly what we want.
                        const range = document.createRange();
                        range.setStart(target, 0);
                        range.collapse(true);
                        const sel = window.getSelection();
                        sel.removeAllRanges();
                        sel.addRange(range);
                        editor.focus();
                        return {
                            ok: true,
                            tag: target.tagName,
                            snippet: (target.textContent || '').slice(0, 40),
                        };
                    }""",
                    block_idx,
                )
                if not (placed or {}).get("ok"):
                    logger.warning(
                        "caret positioning failed at H2 block %d: %s — "
                        "skipping this image to avoid mangling layout",
                        block_idx, placed,
                    )
                    continue
                logger.debug(
                    "caret set below H2 @ block %d → %s (%r)",
                    block_idx, placed.get("tag"), placed.get("snippet"),
                )
                page.wait_for_timeout(200)

                self._upload_image(path)
                logger.info(
                    "inline image uploaded near H2 block %d: %s",
                    block_idx, path,
                )
                # Caption: note.com strips <em>/<small> on paste and
                # ignores Ctrl+I, so plain-text attempts render as
                # normal body-size <p>. The figure node however ships
                # with an empty <figcaption> slot that note styles as
                # a small centred italic-like caption natively — focus
                # that slot and type there.
                #
                # 2026-04-28 fix: image upload's DOM mutation can lag
                # behind Playwright by 500ms+. Poll up to 2s for an
                # empty figcaption before declaring failure. If we
                # truly can't find one, **skip the caption entirely**
                # rather than typing an orphan "※イメージ画像" paragraph
                # at the caret — the orphan text appearing alone above
                # the body was a real reader-visible bug.
                focus_js = """() => {
                    const caps = document.querySelectorAll(
                        '.ProseMirror figure figcaption'
                    );
                    let target = null;
                    for (let i = caps.length - 1; i >= 0; i--) {
                        if (!(caps[i].textContent || '').trim()) {
                            target = caps[i];
                            break;
                        }
                    }
                    if (!target) return false;
                    const range = document.createRange();
                    range.selectNodeContents(target);
                    range.collapse(true);
                    const sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                    try { target.focus(); } catch (e) {}
                    return true;
                }"""
                focused = False
                for attempt in range(5):  # poll up to ~2.5s total
                    page.wait_for_timeout(500)
                    if page.evaluate(focus_js):
                        focused = True
                        break
                if focused:
                    page.keyboard.type("※イメージ画像", delay=4)
                    page.wait_for_timeout(200)
                    # Leave the figcaption so subsequent uploads don't
                    # append inside the same caption slot.
                    page.keyboard.press("ArrowDown")
                    page.wait_for_timeout(100)
                else:
                    # No figcaption — skip caption entirely to avoid
                    # the orphan-text bug. The image still publishes;
                    # readers just don't see the small "※イメージ画像"
                    # subtitle which is acceptable graceful degradation.
                    logger.warning(
                        "figcaption not found for block %d — "
                        "skipping caption (no orphan text injected)",
                        block_idx,
                    )
            except Exception as exc:
                logger.warning(
                    "inline image upload failed (%s): %s", path, exc
                )
        page.wait_for_timeout(800)

    # Trust boundary for any image path passed to upload helpers. The
    # cover_image_path parameter flows from JSON files / CLI args and
    # eventually hits set_input_files() / read_bytes() — without this
    # gate an attacker (or a corrupted JSON) could upload arbitrary
    # local files (SSH keys, cookies, env secrets) to note's CDN.
    _ALLOWED_IMAGE_DIRS: tuple[str, ...] = (
        "data/images",
        "docs/images",
    )
    _ALLOWED_IMAGE_EXTS: tuple[str, ...] = (
        ".png", ".jpg", ".jpeg", ".webp", ".gif",
    )
    _IMAGE_MAGIC_BYTES: tuple[bytes, ...] = (
        b"\x89PNG\r\n\x1a\n",   # PNG
        b"\xff\xd8\xff",        # JPEG (any variant)
        b"GIF87a", b"GIF89a",   # GIF
        b"RIFF",                # WEBP container (further check via "WEBP" at offset 8)
    )
    _MAX_IMAGE_BYTES: int = 20 * 1024 * 1024  # 20 MB ceiling

    @classmethod
    def _validate_image_path(cls, file_path: str) -> Path:
        """Reject any path that isn't a small, real image under our
        data/images or docs/images trees. Returns the resolved Path
        on success; raises ValueError otherwise.

        Why this gate exists:
        * `set_input_files()` and `read_bytes()` will happily ingest
          ``../../../.ssh/id_ed25519`` or similar if the JSON spec
          (or a malicious CLI arg) says so — `cover_image_path` flows
          unchecked from `data/articles/note-*.json::cover_image`.
        * Stem checks (``endswith(".png")``) are not enough: an
          attacker could rename a binary blob. We sniff the leading
          bytes against the small set of formats note actually
          supports.
        """
        if not file_path:
            raise ValueError("image path is empty")
        p = Path(file_path).resolve()
        if not p.exists():
            raise ValueError(f"image path does not exist: {p}")
        if not p.is_file():
            raise ValueError(f"image path is not a regular file: {p}")
        size = p.stat().st_size
        if size <= 0:
            raise ValueError(f"image is empty: {p}")
        if size > cls._MAX_IMAGE_BYTES:
            raise ValueError(
                f"image too large ({size} bytes > {cls._MAX_IMAGE_BYTES}): {p}"
            )
        if p.suffix.lower() not in cls._ALLOWED_IMAGE_EXTS:
            raise ValueError(f"image extension not allowed: {p.suffix}")
        # Path-traversal / arbitrary-FS guard: must live under one of
        # the trees we generate into. Repo root == note_publisher.py's
        # parent.parent.
        repo_root = Path(__file__).resolve().parent.parent
        try:
            rel = p.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(
                f"image must live under repo root ({repo_root}): {p}"
            ) from exc
        rel_posix = rel.as_posix()
        if not any(
            rel_posix.startswith(allowed + "/")
            for allowed in cls._ALLOWED_IMAGE_DIRS
        ):
            raise ValueError(
                f"image not in allowlisted dir {cls._ALLOWED_IMAGE_DIRS}: "
                f"{rel_posix}"
            )
        # Magic-bytes sniff. Cheap defence against a renamed payload
        # that just happens to have a .png/.jpg extension.
        head = p.read_bytes()[:16]
        ok = False
        for sig in cls._IMAGE_MAGIC_BYTES:
            if head.startswith(sig):
                if sig == b"RIFF":
                    # WEBP must also have b"WEBP" at offset 8.
                    ok = len(head) >= 12 and head[8:12] == b"WEBP"
                else:
                    ok = True
                break
        if not ok:
            raise ValueError(f"image magic-bytes do not match a known format: {p}")
        return p

    def _set_eyecatch_on_current_page(
        self, file_path: str, force_replace: bool = False,
    ) -> bool:
        """Upload *file_path* as the eyecatch on the currently-open editor.

        Reuses the dual-strategy approach from
        scripts/retrofit_note_covers._attach_cover but operates on the
        page we are already editing — no navigation, no save click.
        Caller is responsible for saving after.

        Args:
            file_path: Absolute path of the image to set as the cover.
            force_replace: When True, skip the "cover already present"
                early-return and attempt to replace the existing cover.
                Required by ``edit_article`` when the whole point of
                the call is to swap in a new thumbnail. Default False
                preserves the original ``publish_article`` idempotent
                behaviour (re-publishes shouldn't duplicate-upload the
                same cover).
        """
        assert self._page is not None
        page = self._page
        try:
            # Trust gate. Reject anything that isn't a real image under
            # our data/docs trees BEFORE handing it to Playwright.
            try:
                validated_path = self._validate_image_path(file_path)
            except ValueError as exc:
                logger.error("eyecatch image rejected: %s", exc)
                return False
            file_path = str(validated_path)

            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)

            # Detect existing cover. In publish_article flow we want
            # idempotency, but edit_article wants to replace.
            already = page.evaluate(
                """() => !document.querySelector('[aria-label="画像を追加"]')"""
            )

            # Force-replace path: note's editor floats a toolbar with a
            # ``aria-label="削除"`` button above the selected eyecatch.
            # Clicking the image first forces selection / selects the
            # figure node, then clicking 削除 removes the cover. After
            # removal the ``画像を追加`` button reappears and the
            # Strategy A/B upload paths below can take over.
            if already and force_replace:
                logger.info("force_replace: deleting existing eyecatch")
                try:
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(300)
                    # Note's editor renders an `aria-label="削除"` X-button
                    # overlaid on the eyecatch (top-right corner). It is
                    # visible without a hover and a JS-side click on it
                    # removes the cover. Find the one whose centre is
                    # inside the eyecatch-image bounding box (other 削除
                    # elements may exist for inline images / tags).
                    deleted = page.evaluate(
                        """() => {
                            const img = document.querySelector('img[alt="eyecatch"]');
                            if (!img) return 'no-eyecatch-img';
                            const ir = img.getBoundingClientRect();
                            const cands = Array.from(
                                document.querySelectorAll('[aria-label="削除"]')
                            );
                            for (const el of cands) {
                                const r = el.getBoundingClientRect();
                                const cx = r.left + r.width / 2;
                                const cy = r.top + r.height / 2;
                                if (
                                    cx >= ir.left && cx <= ir.right &&
                                    cy >= ir.top && cy <= ir.bottom
                                ) {
                                    const target = el.closest('button') || el;
                                    target.click();
                                    return 'clicked';
                                }
                            }
                            return 'no-delete-button';
                        }"""
                    )
                    logger.info("eyecatch delete: %s", deleted)
                    if deleted not in ("clicked",):
                        # If we can't locate the eyecatch image OR its
                        # adjacent delete button, do NOT continue to
                        # upload — the page state is unexpected and
                        # uploading would risk attaching the cover to
                        # a body file-input or simply layering a new
                        # eyecatch on top of the old one.
                        logger.error(
                            "force_replace abort: %s (page state unsafe)",
                            deleted,
                        )
                        return False
                    page.wait_for_timeout(800)
                    # Some note UI versions show a confirm dialog.
                    confirm = page.evaluate(
                        """() => {
                            const ok = Array.from(
                                document.querySelectorAll('button')
                            ).find(b => /削除する|削除$|OK|はい/.test(
                                b.textContent.trim()
                            ));
                            if (ok) {ok.click(); return ok.textContent.trim();}
                            return null;
                        }"""
                    )
                    logger.info("confirm dialog click: %r", confirm)
                    page.wait_for_timeout(1500)
                    already = page.evaluate(
                        """() => !document.querySelector(
                            '[aria-label="画像を追加"]'
                        )"""
                    )
                    logger.info("after delete: already=%s", already)
                except Exception as exc:
                    logger.warning("eyecatch delete attempt failed: %s", exc)

            if already and not force_replace:
                logger.info("eyecatch already present; skipping upload")
                return True

            # Strategy A: hidden file input scoped to the eyecatch
            # dropzone. Without scoping we'd iterate every <input
            # type=file> on the page (note editor has several — body
            # inline image, custom uploaders, etc.) and post the cover
            # to whichever accepted first. Cross-contamination risk:
            # the cover would render as an inline body image while
            # the eyecatch slot stayed empty.
            scoped_handles = page.evaluate_handle(
                """() => {
                    const btn = document.querySelector('[aria-label="画像を追加"]');
                    if (!btn) return [];
                    let host = btn;
                    for (let depth = 0; depth < 6 && host; depth++) {
                        const inputs = host.querySelectorAll('input[type="file"]');
                        if (inputs.length) return Array.from(inputs);
                        host = host.parentElement;
                    }
                    return [];
                }"""
            )
            scoped_inputs: list = []
            try:
                length = scoped_handles.evaluate("a => a.length") or 0
                for i in range(length):
                    scoped_inputs.append(
                        scoped_handles.evaluate_handle(
                            "(a, idx) => a[idx]", i,
                        ).as_element()
                    )
            except Exception as exc:
                logger.debug("scoped file_input lookup failed: %s", exc)
            for fi in scoped_inputs:
                if fi is None:
                    continue
                try:
                    fi.set_input_files(file_path)
                    page.wait_for_timeout(2500)
                    self._dismiss_crop_modal()
                    page.wait_for_timeout(800)
                    logger.info(
                        "eyecatch uploaded via scoped file input: %s",
                        file_path,
                    )
                    return True
                except Exception as exc:
                    logger.debug("scoped file input rejected: %s", exc)
                    continue

            # Strategy B: synthetic drop event onto the eyecatch dropzone.
            import base64
            data = Path(file_path).read_bytes()
            b64 = base64.b64encode(data).decode()
            mime = "image/png" if file_path.lower().endswith(".png") else "image/jpeg"
            result = page.evaluate(
                """({b64, name, mime}) => {
                    const byteString = atob(b64);
                    const ab = new ArrayBuffer(byteString.length);
                    const ia = new Uint8Array(ab);
                    for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
                    const blob = new Blob([ab], {type: mime});
                    const file = new File([blob], name, {type: mime});
                    const dt = new DataTransfer();
                    dt.items.add(file);
                    const btn = document.querySelector('[aria-label="画像を追加"]');
                    if (!btn) return 'no-button';
                    const zone = btn.closest('[data-dragging]') || btn.closest('div') || btn.parentElement;
                    if (!zone) return 'no-zone';
                    const rect = zone.getBoundingClientRect();
                    const cx = rect.left + rect.width / 2;
                    const cy = rect.top + rect.height / 2;
                    for (const type of ['dragenter', 'dragover', 'drop']) {
                        const ev = new DragEvent(type, {
                            bubbles: true, cancelable: true,
                            clientX: cx, clientY: cy, dataTransfer: dt,
                        });
                        try { Object.defineProperty(ev, 'dataTransfer', {value: dt}); } catch (_) {}
                        zone.dispatchEvent(ev);
                    }
                    return 'ok';
                }""",
                {"b64": b64, "name": Path(file_path).name, "mime": mime},
            )
            if result == "ok":
                page.wait_for_timeout(4000)
                self._dismiss_crop_modal()
                page.wait_for_timeout(800)
                logger.info("eyecatch uploaded via drop event: %s", file_path)
                return True
            logger.warning("eyecatch upload failed: %s", result)
            return False
        except Exception as exc:
            logger.warning("eyecatch upload exception: %s", exc)
            return False

    @staticmethod
    def _markdown_to_html_for_note(content: str) -> str:
        """Convert article markdown to HTML suitable for note pasting.

        Runs the same pre-processing as the plain-text path (mermaid
        already handled, images already stripped) and then uses the
        ``markdown`` package to convert headings, lists, emphasis,
        blockquotes, and most importantly inline links into real
        ``<a href="...">text</a>`` elements. Tables are included via
        the ``tables`` extension.

        The emoji stripper is still run so note's AI-detection heuristics
        do not flag the post.
        """
        import markdown as _md
        text = NotePublisher._strip_emojis(content)
        html = _md.markdown(
            text,
            extensions=["extra", "sane_lists", "tables", "nl2br"],
        )
        return html

    @staticmethod
    def _paste_html(page, html: str) -> None:
        """Write *html* to the clipboard as text/html then Ctrl+V.

        Uses the async Clipboard API via :meth:`Page.evaluate` so the
        browser sees a genuine rich-text payload. note's ProseMirror
        editor parses the HTML on paste and constructs proper
        headings, lists, emphasis and anchor marks — none of the
        keyboard-dialog gymnastics the Ctrl+K flow required.
        """
        try:
            page.evaluate(
                """async (html) => {
                    const blob = new Blob([html], { type: 'text/html' });
                    const plain = new Blob([html.replace(/<[^>]+>/g, '')], { type: 'text/plain' });
                    const item = new ClipboardItem({
                        'text/html': blob,
                        'text/plain': plain,
                    });
                    await navigator.clipboard.write([item]);
                }""",
                html,
            )
        except Exception as exc:
            logger.warning("HTML clipboard write failed: %s — falling back to plain text paste", exc)
            page.evaluate(
                "async (t) => { await navigator.clipboard.writeText(t); }",
                html,
            )
        page.keyboard.press("Control+v")

    @staticmethod
    def _paste_text(page, text: str) -> None:
        """Write *text* to the OS clipboard and trigger Ctrl+V.

        Used instead of ``keyboard.type`` for URLs because the latter
        interprets certain characters through the current keyboard
        layout — a URL with ``?`` and ``&`` can land as different
        glyphs on non-US layouts, breaking the link. Clipboard paste
        bypasses the layout entirely.
        """
        try:
            page.evaluate(
                "async (t) => { await navigator.clipboard.writeText(t); }",
                text,
            )
            page.keyboard.press("Control+v")
            return
        except Exception:
            # Fallback: type character-by-character if clipboard write
            # is blocked by the browser context permissions.
            page.keyboard.type(text, delay=4)

    @staticmethod
    def _markdown_to_plain(content: str, preserve_links: bool = False) -> str:
        """Convert markdown syntax to plain text for note editor.

        note.com's ProseMirror editor does not parse markdown input, so
        we need to strip markdown syntax. Headings become bare text with
        blank-line spacing; bold/italic markers are removed.

        Links behave differently depending on *preserve_links*:

        - ``preserve_links=False`` (default, back-compat): each
          ``[text](url)`` is flattened to ``text (url)`` plain text.
        - ``preserve_links=True``: ``[text](url)`` markers are left
          untouched so the caller can later type them via the
          Ctrl+K link-dialog flow and get a real embedded link.
        """
        lines = content.split("\n")
        result = []
        for line in lines:
            stripped = line.rstrip()

            # Heading: "## Title" → "■ Title" (visual bullet for plain text editor)
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                # Add blank line before heading if not already there
                if result and result[-1].strip():
                    result.append("")
                # Use different markers for hierarchy
                if level <= 2:
                    marker = "■ "
                elif level == 3:
                    marker = "▶ "
                else:
                    marker = "・ "
                result.append(f"{marker}{title_text}")
                result.append("")
                continue

            # Unordered list: "- item" / "* item" → "・item"
            list_match = re.match(r"^(\s*)[-*+]\s+(.+)$", stripped)
            if list_match:
                indent = list_match.group(1)
                item = list_match.group(2).strip()
                result.append(f"{indent}・{item}")
                continue

            # Ordered list: "1. item" → "・item" (drop the number marker).
            # Note's editor auto-enters list mode on "1. " which interacts
            # badly with subsequent Enter keystrokes from the Playwright
            # typing path — Mid-list typing can stall. Converting to the
            # same bullet style as unordered lists side-steps it.
            ordered_match = re.match(r"^(\s*)\d+\.\s+(.+)$", stripped)
            if ordered_match:
                indent = ordered_match.group(1)
                item = ordered_match.group(2).strip()
                result.append(f"{indent}・{item}")
                continue

            result.append(stripped)

        text = "\n".join(result)

        # Step 0: Convert **bold** to visually bold using full-width or emphasis chars
        # Note's ProseMirror doesn't render markdown, so we use Unicode fullwidth
        # for bold words and add 「」quotes for emphasis
        def _emphasize_bold(m: re.Match[str]) -> str:
            inner = m.group(1)
            return f"【{inner}】"
        # Run bold conversion BEFORE removing markdown (before step 1)

        # Step 1: Extract code blocks (```...```) to placeholders to protect them
        code_blocks: list[str] = []
        def _save_code_block(m: re.Match[str]) -> str:
            code_blocks.append(m.group(1))
            return f"\x00CODEBLOCK{len(code_blocks)-1}\x00"

        text = re.sub(r"```[^\n]*\n(.*?)\n```", _save_code_block, text, flags=re.DOTALL)
        text = text.replace("```", "")  # orphan fences

        # Step 2: Extract inline code (`...`) similarly
        inline_codes: list[str] = []
        def _save_inline(m: re.Match[str]) -> str:
            inline_codes.append(m.group(1))
            return f"\x00INLINE{len(inline_codes)-1}\x00"

        text = re.sub(r"`([^`\n]+?)`", _save_inline, text)

        # Step 3: Convert **bold** to Unicode mathematical sans-serif bold
        # This actually renders visually thicker in the plain text editor
        def _to_bold(m: re.Match[str]) -> str:
            return NotePublisher._ascii_to_bold(m.group(1))

        text = re.sub(r"\*\*(.+?)\*\*", _to_bold, text)
        text = re.sub(r"__(.+?)__", _to_bold, text)
        # Italic: just strip markers
        text = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"\1", text)
        text = re.sub(r"(?<![_\w])_([^_\n]+?)_(?![_\w])", r"\1", text)

        # Blockquote: "> text" → "text"
        text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)

        # Horizontal rule: --- → blank
        text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)

        # Link: [text](url) — either flattened to "text (url)" for the
        # legacy plain-text path, or left as markdown for the caller to
        # convert into embedded links via the Ctrl+K dialog flow.
        if not preserve_links:
            def _replace_link(m: re.Match[str]) -> str:
                return f"{m.group(1)} ({m.group(2)})"
            text = re.sub(
                r"\[([^\]]+)\]\(((?:[^()]|\([^)]*\))+)\)",
                _replace_link,
                text,
            )

        # Step 4: Restore inline code and code blocks
        for i, code in enumerate(inline_codes):
            text = text.replace(f"\x00INLINE{i}\x00", code)
        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

        # Collapse 3+ blank lines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Remove Unicode emojis (AI-like)
        text = NotePublisher._strip_emojis(text)

        return text.strip()

    @staticmethod
    def _strip_local_images(content: str) -> str:
        """Swap local image references for their remote CDN URL when known.

        Generated articles use the markdown title attribute as a side
        channel: ``![alt](data/images/stock/x.jpg "https://images.unsplash.com/...")``.
        When a remote URL is present we keep the image visible to readers
        by rewriting the local path to the live URL — note's HTML clipboard
        paste then sends a real ``<img src="https://...">`` to the editor,
        which note auto-embeds as a hosted image.

        Local-only image references (no title URL) are still stripped
        because note has no way to access them.
        """
        removed: list[str] = []
        rewritten: list[str] = []

        def _replace(match: re.Match[str]) -> str:
            alt = match.group("alt") or ""
            path = match.group("path") or ""
            title = match.group("title") or ""
            if title and title.startswith("http"):
                rewritten.append(title)
                safe_alt = alt.replace("[", "(").replace("]", ")")
                return f"![{safe_alt}]({title})"
            removed.append(path)
            return ""

        new_content = _LOCAL_IMAGE_RE.sub(_replace, content)

        # Collapse 3+ blank lines into just 2 (paragraph break)
        new_content = re.sub(r"\n{3,}", "\n\n", new_content)
        # Strip trailing whitespace from each line
        new_content = "\n".join(line.rstrip() for line in new_content.split("\n"))

        if rewritten:
            logger.info(
                "ローカル画像 %d 件をCDN URLにスワップしました",
                len(rewritten),
            )
        if removed:
            logger.warning(
                "ローカル画像 %d 件を本文から除外しました: %s",
                len(removed),
                ", ".join(removed[:3]) + ("..." if len(removed) > 3 else ""),
            )
        return new_content

    @staticmethod
    def _drop_local_images(content: str) -> str:
        """Remove every ``![alt](data/images/... "url")`` reference.

        Used when the caller is going to upload the same images inline
        via note's native paste handler — keeping the Markdown would
        just show as literal text because note's ProseMirror will not
        render external ``<img>`` tags.
        """
        dropped = 0

        def _replace(match: re.Match[str]) -> str:
            nonlocal dropped
            dropped += 1
            return ""

        new_content = _LOCAL_IMAGE_RE.sub(_replace, content)
        new_content = re.sub(r"\n{3,}", "\n\n", new_content)
        new_content = "\n".join(line.rstrip() for line in new_content.split("\n"))
        if dropped:
            logger.info(
                "ローカル画像マークダウン %d 件を削除（インライン経路でアップロード予定）",
                dropped,
            )
        return new_content
