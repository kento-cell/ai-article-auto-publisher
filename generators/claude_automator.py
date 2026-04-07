"""Selenium-based Claude.ai browser automation for article generation.

Requires an active Claude.ai session in the Chrome profile specified by
the CHROME_PROFILE_PATH environment variable. The module reuses that
existing login session so no credential handling is needed.

Dependencies: selenium, python-dotenv
"""

import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

logger = logging.getLogger(__name__)

CLAUDE_URL = "https://claude.ai/new"
DEFAULT_TIMEOUT = 120
MAX_RETRIES = 3
RETRY_DELAY = 5


class ClaudeAutomator:
    """Automate interactions with Claude.ai via Selenium WebDriver.

    This class drives a Chrome browser with an existing user profile so
    that the Claude.ai session cookie is already present.  It is **not**
    an API client -- it literally types into the web UI and scrapes the
    response.  Use it only when API access is unavailable.

    Attributes:
        driver: The Selenium WebDriver instance.
        timeout: Maximum seconds to wait for a response.
    """

    def __init__(
        self,
        headless: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise Chrome WebDriver with the user's profile.

        Args:
            headless: Run Chrome without a visible window.
            timeout: Seconds to wait for Claude's response.

        Raises:
            EnvironmentError: If CHROME_PROFILE_PATH is not set.
            WebDriverException: If the driver cannot start.
        """
        self.timeout = timeout

        profile_path = os.getenv("CHROME_PROFILE_PATH")
        if not profile_path:
            raise EnvironmentError(
                "CHROME_PROFILE_PATH environment variable is not set. "
                "Point it to a Chrome profile directory with an active "
                "Claude.ai session."
            )

        options = Options()
        options.add_argument(f"--user-data-dir={profile_path}")
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        try:
            self.driver = webdriver.Chrome(options=options)
            logger.info("Chrome WebDriver initialised (headless=%s).", headless)
        except WebDriverException:
            logger.exception("Failed to start Chrome WebDriver.")
            raise

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def send_prompt(self, prompt: str) -> str:
        """Send a prompt to Claude.ai and return the response text.

        Args:
            prompt: The message to send.

        Returns:
            The text content of Claude's reply.

        Raises:
            TimeoutException: If no response appears within *timeout*.
            RuntimeError: After exhausting retry attempts.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self._send_and_receive(prompt)
            except (TimeoutException, NoSuchElementException) as exc:
                logger.warning(
                    "Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc
                )
                if attempt == MAX_RETRIES:
                    raise RuntimeError(
                        f"Failed to get response after {MAX_RETRIES} retries."
                    ) from exc
                time.sleep(RETRY_DELAY)
        # Unreachable, but keeps mypy happy.
        raise RuntimeError("Unexpected control flow in send_prompt.")

    def generate_article(
        self, template: str, article_data: dict
    ) -> str:
        """Build a prompt from *template* + *article_data* and send it.

        Args:
            template: A Python format-string with ``{key}`` placeholders.
            article_data: Values to fill into the template.

        Returns:
            The generated article text from Claude.
        """
        try:
            prompt = template.format(**article_data)
        except KeyError as exc:
            logger.error("Template placeholder missing in article_data: %s", exc)
            raise

        logger.info("Generating article (prompt length: %d chars).", len(prompt))
        return self.send_prompt(prompt)

    def close(self) -> None:
        """Quit the WebDriver and release resources."""
        try:
            self.driver.quit()
            logger.info("WebDriver closed.")
        except WebDriverException:
            logger.exception("Error while closing WebDriver.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send_and_receive(self, prompt: str) -> str:
        """Navigate, type, wait, and scrape a single exchange."""
        self.driver.get(CLAUDE_URL)
        wait = WebDriverWait(self.driver, self.timeout)

        # Wait for the input area to appear.
        textarea = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div[contenteditable='true']")
            )
        )

        # Type the prompt.
        textarea.click()
        textarea.send_keys(prompt)
        textarea.send_keys(Keys.RETURN)
        logger.debug("Prompt sent; waiting for response.")

        # Wait until a response container appears and stabilises.
        response_el = self._wait_for_stable_response(wait)
        text: str = response_el.text.strip()
        logger.info("Response received (%d chars).", len(text))
        return text

    def _wait_for_stable_response(
        self, wait: WebDriverWait, poll_interval: float = 2.0
    ) -> "webdriver.remote.webelement.WebElement":
        """Wait until the response element stops changing.

        Claude streams tokens, so we poll until the text length is
        stable for two consecutive checks.
        """
        selector = (By.CSS_SELECTOR, "[data-is-streaming]")
        try:
            wait.until(EC.presence_of_element_located(selector))
        except TimeoutException:
            pass  # Element naming may change; fall through.

        # Fallback: look for the last assistant message block.
        response_selector = (
            By.CSS_SELECTOR,
            "div.font-claude-message",
        )

        previous_length: Optional[int] = None
        stable_count = 0
        deadline = time.monotonic() + self.timeout

        while time.monotonic() < deadline:
            elements = self.driver.find_elements(*response_selector)
            if not elements:
                time.sleep(poll_interval)
                continue

            current_length = len(elements[-1].text)
            if current_length == previous_length and current_length > 0:
                stable_count += 1
                if stable_count >= 3:
                    return elements[-1]
            else:
                stable_count = 0
            previous_length = current_length
            time.sleep(poll_interval)

        raise TimeoutException("Response did not stabilise within timeout.")
