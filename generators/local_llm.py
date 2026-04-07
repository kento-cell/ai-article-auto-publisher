"""Ollama / CodeLlama integration for local LLM inference.

Used as a fallback when Claude.ai is unavailable, or for lightweight
code-generation tasks that do not require a frontier model.

Dependencies: requests, python-dotenv
"""

import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma3:12b"
DEFAULT_TIMEOUT = 300  # seconds -- local generation can be slow


class LocalLLM:
    """Client for the Ollama REST API.

    Attributes:
        base_url: Root URL of the Ollama server.
        default_model: Model name used when none is specified.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise the Ollama client.

        Args:
            base_url: Ollama API root.  Falls back to the
                ``OLLAMA_API_URL`` env var, then ``http://localhost:11434``.
            default_model: Model to use by default.
            timeout: HTTP timeout in seconds.
        """
        self.base_url = (
            base_url
            or os.getenv("OLLAMA_API_URL")
            or DEFAULT_OLLAMA_URL
        ).rstrip("/")
        self.default_model = default_model
        self.timeout = timeout
        logger.info(
            "LocalLLM initialised (url=%s, model=%s).",
            self.base_url,
            self.default_model,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return *True* if the Ollama server is reachable.

        Sends a lightweight GET to the server root and checks for a
        200 response.
        """
        try:
            resp = requests.get(self.base_url, timeout=5)
            available = resp.status_code == 200
            logger.debug("Ollama health check: available=%s", available)
            return available
        except requests.RequestException as exc:
            logger.warning("Ollama health check failed: %s", exc)
            return False

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        """Generate a completion from the Ollama API.

        Args:
            prompt: The input prompt.
            model: Override the default model for this call.
            temperature: Sampling temperature.

        Returns:
            The generated text.

        Raises:
            ConnectionError: If the server is unreachable.
            RuntimeError: On a non-200 HTTP response.
        """
        model = model or self.default_model
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }

        logger.info(
            "Requesting generation (model=%s, prompt_len=%d).",
            model,
            len(prompt),
        )

        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            logger.error("Ollama request failed at %s: %s", self.base_url, exc)
            raise ConnectionError(
                f"Ollama request failed at {self.base_url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            logger.error(
                "Ollama returned HTTP %d: %s", resp.status_code, resp.text
            )
            raise RuntimeError(
                f"Ollama API error (HTTP {resp.status_code}): {resp.text}"
            )

        data = resp.json()
        text: str = data.get("response", "")
        logger.info("Generation complete (%d chars).", len(text))
        return text

    def generate_code(
        self,
        description: str,
        language: str = "python",
        model: Optional[str] = None,
    ) -> str:
        """Generate source code from a natural-language description.

        Wraps :meth:`generate` with a system-style prompt that asks the
        model to return only code.

        Args:
            description: What the code should do.
            language: Target programming language.
            model: Override the default model.

        Returns:
            The generated code as a string.
        """
        prompt = (
            f"You are an expert {language} developer.\n"
            f"Write clean, well-documented {language} code for the "
            f"following requirement.  Return ONLY the code, no "
            f"explanation.\n\n"
            f"Requirement:\n{description}"
        )
        return self.generate(prompt, model=model, temperature=0.2)
