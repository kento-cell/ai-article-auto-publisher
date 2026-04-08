"""note.com article publisher using Playwright browser automation.

Automates the note.com editor to create and publish articles, with
support for paid article pricing tiers based on A/B/C quality grades.

Login state is persisted via a Playwright user data directory located at
``data/note-profile``. Run ``scripts/note_login.py`` once to authenticate.
"""

from __future__ import annotations

import logging
import re
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

from generators.note_content_converter import NoteContentConverter

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
# ![alt](./data/images/xxx.png)
_LOCAL_IMAGE_RE: Final[re.Pattern[str]] = re.compile(
    r"!\[[^\]]*\]\(\s*\.?/?(data/images/[^)\s]+)\s*\)"
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
        # Convert tables → keep as markdown (note renders tables natively)
        content = self._mermaid_to_ascii(content)

        # Strip any local image references
        content = self._strip_local_images(content)

        self._ensure_started()
        assert self._page is not None

        try:
            self._assert_logged_in()
            self._navigate_to_editor()
            self._input_title(title)
            self._input_content(content)
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

    @staticmethod
    def _strip_local_images(content: str) -> str:
        """Remove local image references and clean up surrounding whitespace."""
        removed: list[str] = []

        def _replace(match: re.Match[str]) -> str:
            removed.append(match.group(1))
            return ""

        new_content = _LOCAL_IMAGE_RE.sub(_replace, content)

        # Collapse 3+ blank lines into just 2 (paragraph break)
        new_content = re.sub(r"\n{3,}", "\n\n", new_content)
        # Strip trailing whitespace from each line
        new_content = "\n".join(line.rstrip() for line in new_content.split("\n"))

        if removed:
            logger.warning(
                "ローカル画像 %d 件を本文から除外しました: %s",
                len(removed),
                ", ".join(removed[:3]) + ("..." if len(removed) > 3 else ""),
            )
        return new_content
