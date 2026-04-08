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

    def __init__(self, headless: bool = True) -> None:
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
        # Convert mermaid/tables to images
        converter = NoteContentConverter()
        content = converter.convert(content, slug)

        # Extract local image paths for upload (don't strip yet)
        image_paths = self._extract_local_images(content)

        self._ensure_started()
        assert self._page is not None

        try:
            self._assert_logged_in()
            self._navigate_to_editor()
            self._input_title(title)
            self._input_content_with_images(content, image_paths)
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
        if not page.url.startswith(_NOTE_EDITOR_URL):
            page.goto(_NOTE_EDITOR_URL, wait_until="domcontentloaded")

        if "captcha" in page.url.lower():
            raise RuntimeError(
                "note.comでCAPTCHAが表示されました。"
                "headless=Falseで手動対応してください"
            )

        # Wait for either the title input or the ProseMirror body.
        page.wait_for_selector(
            "input[placeholder*='タイトル'], textarea[placeholder*='タイトル'], "
            ".ProseMirror, [contenteditable='true']",
            timeout=_NAV_TIMEOUT_MS,
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
        """Upload an image to note.com editor via file chooser."""
        assert self._page is not None
        page = self._page

        # note editor typically has a "+" button to insert media
        # or a toolbar image button
        image_button_selectors = [
            "button[aria-label*='画像']",
            "button[aria-label*='image']",
            "[data-testid='insert-image']",
            "button:has-text('画像')",
        ]

        # Try clicking an insert-image button that triggers file chooser
        for selector in image_button_selectors:
            btn = page.locator(selector).first
            try:
                btn.wait_for(state="visible", timeout=2_000)
            except PlaywrightTimeoutError:
                continue
            try:
                with page.expect_file_chooser(timeout=5_000) as fc_info:
                    btn.click()
                chooser = fc_info.value
                chooser.set_files(file_path)
                # Wait for upload to complete
                page.wait_for_timeout(2_000)
                return
            except PlaywrightTimeoutError:
                continue

        # Fallback: try direct file input
        file_input = page.locator("input[type='file']").first
        try:
            file_input.set_input_files(file_path)
            page.wait_for_timeout(2_000)
            return
        except PlaywrightError as e:
            raise RuntimeError(f"画像アップロードボタンが見つかりません: {e}") from e

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

        publish_selectors = [
            "button:has-text('投稿する')",
            "button:has-text('公開する')",
            "button:has-text('有料販売する')",
            "[data-testid='publish-button']",
        ]
        clicked = False
        for selector in publish_selectors:
            loc = page.locator(selector).first
            try:
                loc.wait_for(state="visible", timeout=5_000)
            except PlaywrightTimeoutError:
                continue
            loc.click()
            clicked = True
            break
        if not clicked:
            raise RuntimeError("投稿ボタンが見つかりません")

        # Some flows show a confirmation dialog with another 投稿する button.
        try:
            confirm = page.locator(
                "button:has-text('投稿する'), button:has-text('公開する')"
            ).last
            confirm.wait_for(state="visible", timeout=3_000)
            confirm.click()
        except PlaywrightTimeoutError:
            pass
        except PlaywrightError:
            pass

        # Wait for navigation to the published article page (URL contains /n/).
        try:
            page.wait_for_url("**/n/**", timeout=_PUBLISH_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.warning(
                "公開後のリダイレクトを検出できませんでした。現在のURLを返します"
            )
        return page.url

    # ------------------------------------------------------------------
    # Private helpers — content preprocessing
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_local_images(content: str) -> str:
        """Remove local image references that cannot be uploaded inline.

        note.com requires images to be uploaded via its own picker. Rather
        than crash on missing uploads, we drop ``![](data/images/...)``
        references and log a warning.
        """
        removed: list[str] = []

        def _replace(match: re.Match[str]) -> str:
            removed.append(match.group(1))
            return ""

        new_content = _LOCAL_IMAGE_RE.sub(_replace, content)
        if removed:
            logger.warning(
                "ローカル画像 %d 件を本文から除外しました: %s",
                len(removed),
                ", ".join(removed[:3]) + ("..." if len(removed) > 3 else ""),
            )
        return new_content
