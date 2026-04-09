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

    @staticmethod
    def _sanitize_mermaid(content: str) -> str:
        """Convert mermaid code blocks to ASCII arrow flows.

        Gemma3 often generates invalid mermaid syntax like
        `D[出力 (3D/4D)]` (parens inside brackets) which causes
        Zenn mermaid rendering to fail. Convert to simple ASCII.
        """
        import re as _re
        mermaid_re = _re.compile(r"```mermaid\s*\n(.*?)```", _re.DOTALL)

        def _replace(m: _re.Match[str]) -> str:
            src = m.group(1).strip()
            # Parse edges: A[Label] --> B[Label] or A --> B
            edge_re = _re.compile(
                r"(\w+)(?:\[([^\]]+)\])?\s*-->\s*(\w+)(?:\[([^\]]+)\])?"
            )
            edges = edge_re.findall(src)
            if not edges:
                return "```\n" + src + "\n```"
            nodes = []
            for s, sl, d, dl in edges:
                src_name = sl or s
                dst_name = dl or d
                if not nodes:
                    nodes.append(src_name)
                nodes.append(dst_name)
            if len(" → ".join(nodes)) <= 60:
                return "```\n" + " → ".join(nodes) + "\n```"
            # Vertical flow
            lines = []
            for i, n in enumerate(nodes):
                lines.append(f"  [{n}]")
                if i < len(nodes) - 1:
                    lines.append("    │")
                    lines.append("    ▼")
            return "```\n" + "\n".join(lines) + "\n```"

        return mermaid_re.sub(_replace, content)

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
        # Convert mermaid to ASCII (Gemma3 often generates invalid mermaid
        # with special chars in node labels causing syntax errors)
        content = self._sanitize_mermaid(content)

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

            # Step 1: Click "スクラップを作成" to create scrap with title only
            # Zenn scrap creation is 2-step: title → create → add first post
            page.wait_for_timeout(1000)
            submit_selectors = [
                "button:has-text('スクラップを作成')",
                "button:has-text('作成する')",
                "button:has-text('作成')",
                "button[type='submit']",
            ]
            submitted = False
            for sel in submit_selectors:
                try:
                    btns = page.locator(sel).all()
                    for btn in btns:
                        try:
                            if btn.is_visible(timeout=1000):
                                btn.scroll_into_view_if_needed(timeout=2000)
                                btn.click(timeout=3000)
                                submitted = True
                                logger.info("Scrap create via: %s", sel)
                                break
                        except Exception:
                            continue
                    if submitted:
                        break
                except Exception:
                    continue
            if not submitted:
                try:
                    page.screenshot(
                        path=str(_REPO_ROOT / "logs" / "scrap_submit_failed.png"),
                        full_page=True,
                    )
                except Exception:
                    pass
                raise RuntimeError("スクラップ作成ボタンが見つかりません")

            # Step 2: Wait for redirect to scrap page, then add first post
            try:
                page.wait_for_url("**/scraps/**", timeout=30_000)
                # Make sure it's not still /scraps/new
                if page.url.endswith("/scraps/new"):
                    page.wait_for_url(lambda u: "/scraps/" in u and not u.endswith("/new"), timeout=15_000)
            except PlaywrightTimeoutError:
                logger.warning("Scrap page navigation timeout: %s", page.url)

            scrap_url = page.url
            logger.info("Scrap created: %s", scrap_url)
            page.wait_for_timeout(3000)

            # Step 3: Fill first post via CodeMirror 6 editor
            # CM6 accepts page.keyboard.insert_text (NOT type or paste)
            try:
                editor = page.locator(".cm-content").first
                editor.wait_for(state="visible", timeout=10000)
                editor.click()
                page.wait_for_timeout(500)

                # Clear any autosaved draft first
                page.keyboard.press("Control+a")
                page.wait_for_timeout(200)
                page.keyboard.press("Delete")
                page.wait_for_timeout(300)

                # Insert content line by line to preserve newlines
                # (insert_text doesn't handle \n automatically in CM6)
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if line:
                        page.keyboard.insert_text(line)
                    if i < len(lines) - 1:
                        page.keyboard.press("Enter")
                    page.wait_for_timeout(30)

                logger.info("Post body inserted (%d chars)", len(content))
                page.wait_for_timeout(1500)

                # Verify
                inserted = page.evaluate(
                    "() => document.querySelector('.cm-content')?.textContent || ''"
                )
                if not inserted.strip():
                    logger.warning("Body still empty after insert_text")

                # Click the primary "投稿する" submit button
                # Use the specific class — NOT the AddNewMenu button
                post_submitted = False
                primary_selectors = [
                    "button.Button_primary__VcoA9:has-text('投稿する')",
                    "button[class*='Button_primary']:has-text('投稿する')",
                ]
                for sel in primary_selectors:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=2000):
                            disabled = btn.evaluate("el => el.disabled")
                            if not disabled:
                                btn.scroll_into_view_if_needed(timeout=2000)
                                btn.click(timeout=3000)
                                post_submitted = True
                                logger.info("Primary 投稿する clicked: %s", sel)
                                page.wait_for_timeout(3000)
                                break
                    except Exception:
                        continue

                # Fallback: pick the LAST 投稿する button (primary is usually last)
                if not post_submitted:
                    btns = page.locator("button:has-text('投稿する')").all()
                    if btns:
                        btn = btns[-1]
                        try:
                            btn.scroll_into_view_if_needed(timeout=2000)
                            btn.click(timeout=3000)
                            post_submitted = True
                            logger.info("Last 投稿する clicked (fallback)")
                            page.wait_for_timeout(3000)
                        except Exception as e:
                            logger.warning("Fallback click failed: %s", e)

                if not post_submitted:
                    logger.warning("投稿する button not clickable")
                    try:
                        page.screenshot(
                            path=str(_REPO_ROOT / "logs" / "scrap_post_failed.png"),
                            full_page=True,
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("First post creation failed: %s", e)
                try:
                    page.screenshot(
                        path=str(_REPO_ROOT / "logs" / "scrap_post_failed.png"),
                        full_page=True,
                    )
                except Exception:
                    pass

            return scrap_url

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
