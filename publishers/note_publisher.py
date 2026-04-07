"""note.com article publisher using Selenium browser automation.

Automates the note.com editor to create and publish articles, with
support for paid article pricing tiers based on A/B/C quality grades.
"""

import logging
import os
import time
from typing import Final

from generators.note_content_converter import NoteContentConverter
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

# Price tiers by grade combination (overall_grade, evidence_level) -> price_yen.
# Grades are "A", "B", or "C".
_PRICE_TIERS: Final[dict[tuple[str, str], int]] = {
    ("A", "A"): 1980,  # premium
    ("A", "B"): 980,
    ("B", "A"): 500,
    ("B", "B"): 300,
    # All other combinations (C in either position): free
}


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
        slug: str = "article",
    ) -> str:
        """Create and publish an article on note.com.

        Args:
            title: Article title.
            content: Article body text (plain text or HTML).
            tags: List of tags to attach.
            price: Price in JPY. ``0`` means free.
            slug: Article slug for naming generated image files.

        Returns:
            URL of the published article.

        Raises:
            TimeoutException: If a page element is not found in time.
            WebDriverException: On unexpected browser errors.
        """
        try:
            # Convert mermaid diagrams and tables to images for note.com
            converter = NoteContentConverter()
            content = converter.convert(content, slug)

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
    def determine_price(overall_grade: str, evidence_level: str) -> int:
        """Calculate the article price from quality grades.

        Pricing tiers (by overall_grade + evidence_level):
          A + A evidence: 1,980 yen (premium)
          A + B evidence: 980 yen
          B + A evidence: 500 yen
          B + B evidence: 300 yen
          Otherwise: free

        Args:
            overall_grade: "A", "B", or "C".
            evidence_level: "A", "B", or "C".

        Returns:
            Price in JPY.
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
        browser_binary = os.environ.get("BROWSER_BINARY_PATH")
        if browser_binary:
            options.binary_location = browser_binary
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
