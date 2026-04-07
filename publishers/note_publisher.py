"""note.com article publisher using Selenium browser automation.

Automates the note.com editor to create and publish articles, with
support for paid article pricing tiers based on quality score.
"""

import logging
import os
import time
from typing import Final

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOTE_EDITOR_URL: Final[str] = "https://note.com/notes/new"
_PAGE_LOAD_TIMEOUT: Final[int] = 30
_ELEMENT_WAIT: Final[int] = 15

# Price tiers: (min_score, price_yen)
_PRICE_TIERS: Final[list[tuple[int, int]]] = [
    (2000, 1980),
    (1500, 980),
    (1000, 500),
    (700, 300),
]


class NotePublisher:
    """Publish articles to note.com via Selenium-driven Chrome.

    The publisher expects an existing Chrome user profile that is already
    logged in to note.com.  The profile path is read from the
    ``CHROME_PROFILE_PATH`` environment variable, or can be supplied
    directly.

    Args:
        chrome_profile_path: Path to the Chrome user-data directory.
            Falls back to ``CHROME_PROFILE_PATH`` env var.

    Raises:
        WebDriverException: If Chrome cannot be started.
    """

    def __init__(self, chrome_profile_path: str | None = None) -> None:
        profile = chrome_profile_path or os.environ.get("CHROME_PROFILE_PATH")
        self._driver = self._create_driver(profile)
        logger.info("NotePublisher initialised")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def publish_article(
        self,
        title: str,
        content: str,
        tags: list[str],
        price: int = 0,
    ) -> str:
        """Create and publish an article on note.com.

        Args:
            title: Article title.
            content: Article body text (plain text or HTML).
            tags: List of tags to attach.
            price: Price in JPY. ``0`` means free.

        Returns:
            URL of the published article.

        Raises:
            TimeoutException: If a page element is not found in time.
            WebDriverException: On unexpected browser errors.
        """
        try:
            self._navigate_to_editor()
            self._input_title(title)
            self._input_content(content)
            self._input_tags(tags)
            if price > 0:
                self._set_price(price)
            url = self._click_publish()
            logger.info("Article published: %s", url)
            return url
        except (TimeoutException, WebDriverException):
            logger.exception("Failed to publish article: %s", title)
            raise

    @staticmethod
    def determine_price(quality_score: float, word_count: int) -> int:
        """Calculate the article price tier from quality metrics.

        Pricing tiers (by *quality_score*):

        * < 700 : free (0)
        * 700--999 : 300 yen
        * 1000--1499 : 500 yen
        * 1500--1999 : 980 yen
        * 2000+ : 1,980 yen

        Args:
            quality_score: Numeric quality score of the article.
            word_count: Total word count (reserved for future rules).

        Returns:
            Price in JPY.
        """
        _ = word_count  # reserved for future adjustments
        for min_score, price_yen in _PRICE_TIERS:
            if quality_score >= min_score:
                logger.debug(
                    "Score %.1f -> %d yen", quality_score, price_yen
                )
                return price_yen
        return 0

    def close(self) -> None:
        """Quit the browser and release resources."""
        try:
            self._driver.quit()
            logger.info("Browser closed")
        except WebDriverException:
            logger.warning("Browser was already closed or unreachable")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_driver(profile_path: str | None) -> webdriver.Chrome:
        """Build and return a configured Chrome WebDriver instance."""
        options = Options()
        if profile_path:
            options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        service = Service()
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(_PAGE_LOAD_TIMEOUT)
        return driver

    def _wait_for(self, by: str, value: str) -> object:
        """Wait for an element to be present and return it."""
        return WebDriverWait(self._driver, _ELEMENT_WAIT).until(
            EC.presence_of_element_located((by, value))
        )

    def _navigate_to_editor(self) -> None:
        """Open the note.com new-article editor page."""
        logger.debug("Navigating to %s", _NOTE_EDITOR_URL)
        self._driver.get(_NOTE_EDITOR_URL)
        self._wait_for(By.CSS_SELECTOR, "[data-testid='note-editor']")

    def _input_title(self, title: str) -> None:
        """Type the article title into the editor."""
        elem = self._wait_for(
            By.CSS_SELECTOR, "[placeholder*='タイトル']"
        )
        elem.clear()
        elem.send_keys(title)

    def _input_content(self, content: str) -> None:
        """Paste article content into the body editor."""
        elem = self._wait_for(
            By.CSS_SELECTOR, "[data-testid='note-body']"
        )
        elem.click()
        elem.send_keys(content)

    def _input_tags(self, tags: list[str]) -> None:
        """Add tags one by one through the tag input field."""
        try:
            tag_input = self._wait_for(
                By.CSS_SELECTOR, "[data-testid='tag-input']"
            )
        except TimeoutException:
            logger.warning("Tag input not found; skipping tags")
            return
        for tag in tags:
            tag_input.send_keys(tag)
            tag_input.send_keys("\n")
            time.sleep(0.3)

    def _set_price(self, price: int) -> None:
        """Enable paid-article mode and set the price."""
        try:
            paid_toggle = self._wait_for(
                By.CSS_SELECTOR, "[data-testid='paid-toggle']"
            )
            paid_toggle.click()
            price_input = self._wait_for(
                By.CSS_SELECTOR, "[data-testid='price-input']"
            )
            price_input.clear()
            price_input.send_keys(str(price))
            logger.debug("Price set to %d yen", price)
        except (TimeoutException, NoSuchElementException):
            logger.warning("Could not set price; publishing as free")

    def _click_publish(self) -> str:
        """Click the publish button and return the resulting URL."""
        publish_btn = self._wait_for(
            By.CSS_SELECTOR, "[data-testid='publish-button']"
        )
        publish_btn.click()
        # Wait for redirect to the published article page.
        WebDriverWait(self._driver, _PAGE_LOAD_TIMEOUT).until(
            EC.url_contains("/n/")
        )
        return self._driver.current_url
