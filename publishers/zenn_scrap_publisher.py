"""Zenn Scrap auto-publisher via Playwright.

Zenn Scraps don't have a Git-based workflow like articles do; they must
be created through the web UI. This publisher uses Playwright with a
persistent login profile (data/zenn-profile/) to automate that.

Setup: run scripts/zenn_login.py once to authenticate.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

logger = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_PROFILE_DIR: Final[Path] = _REPO_ROOT / "data" / "zenn-profile"

_NEW_SCRAP_URL: Final[str] = "https://zenn.dev/scraps/new"
_NAV_TIMEOUT: Final[int] = 45_000


class ZennScrapPublisher:
    """Post scraps to Zenn via the web editor."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._profile_dir = _PROFILE_DIR
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self) -> "ZennScrapPublisher":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._page = None

    def _ensure_started(self) -> None:
        if self._context is not None:
            return
        if not self._profile_dir.exists():
            raise RuntimeError(
                "Zennログインが必要です。"
                "python scripts/zenn_login.py を実行してください"
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
        self._context.set_default_timeout(_NAV_TIMEOUT)
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )

    def publish_scrap(self, title: str, content: str) -> str:
        """Create a new Zenn scrap with title and initial post content.

        Args:
            title: Scrap title
            content: First post body (markdown)

        Returns:
            URL of the created scrap, or empty string on failure
        """
        self._ensure_started()
        assert self._page is not None
        page = self._page

        try:
            logger.info("Opening Zenn new-scrap editor...")
            page.goto(_NEW_SCRAP_URL, timeout=_NAV_TIMEOUT)
            page.wait_for_timeout(2000)

            if "enter" in page.url or "login" in page.url:
                raise RuntimeError(
                    "Zennログイン切れ。scripts/zenn_login.py を実行してください"
                )

            # Title input — verified selector (2026-04)
            try:
                title_input = page.locator("textarea#scrap-new-title").first
                title_input.wait_for(state="visible", timeout=5000)
                title_input.click()
                title_input.fill(title)
                logger.info("Scrap title filled")
            except Exception as e:
                raise RuntimeError(f"スクラップタイトル入力欄が見つかりません: {e}") from e

            page.wait_for_timeout(500)

            # Body editor — Zenn uses a CodeMirror-based markdown editor.
            # Find the textarea that's NOT the title, or use CodeMirror's content area
            try:
                # Try CodeMirror first
                cm_selectors = [
                    ".cm-content",
                    ".cm-editor .cm-content",
                    ".CodeMirror",
                    "textarea:not(#scrap-new-title)",
                ]
                body_filled = False
                for sel in cm_selectors:
                    try:
                        body = page.locator(sel).first
                        if body.is_visible(timeout=1500):
                            body.click()
                            page.wait_for_timeout(300)
                            page.keyboard.type(content, delay=2)
                            body_filled = True
                            logger.info("Scrap body filled via %s", sel)
                            break
                    except Exception:
                        continue
                if not body_filled:
                    # Last resort: just type after title
                    page.keyboard.press("Tab")
                    page.keyboard.type(content, delay=2)
            except Exception as e:
                logger.warning("本文入力に問題: %s", e)

            page.wait_for_timeout(1000)

            # Submit — click "スクラップを作成"
            try:
                submit_btn = page.locator("button:has-text('スクラップを作成')").first
                submit_btn.wait_for(state="visible", timeout=5000)
                submit_btn.click(timeout=3000)
                logger.info("Scrap create clicked")
            except Exception as e:
                raise RuntimeError(f"スクラップ作成ボタンが見つかりません: {e}") from e

            # Sometimes a confirmation 投稿する appears
            page.wait_for_timeout(1500)
            try:
                post_btn = page.locator("button:has-text('投稿する')").first
                if post_btn.is_visible(timeout=2000):
                    post_btn.click(timeout=3000)
                    logger.info("投稿する clicked")
            except Exception:
                pass

            # Wait for redirect to the new scrap URL
            try:
                page.wait_for_url("**/scraps/**", timeout=30_000)
                if page.url == _NEW_SCRAP_URL:
                    page.wait_for_timeout(3000)
            except PlaywrightTimeoutError:
                logger.warning("スクラップ作成後のリダイレクト未検出: %s", page.url)

            return page.url

        except PlaywrightTimeoutError as e:
            logger.exception("Zennスクラップ作成タイムアウト")
            raise RuntimeError(f"タイムアウト: {e}") from e
        except PlaywrightError as e:
            logger.exception("Zennスクラップ作成エラー")
            raise RuntimeError(f"Playwrightエラー: {e}") from e
