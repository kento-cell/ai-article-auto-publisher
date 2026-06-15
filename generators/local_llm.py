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
# 2026-06-15: baseline flipped gemma3:12b -> gemma4:e4b so EVERY generation
# task (incl. no-arg LocalLLM() bypass sites: image-subject distillation,
# paid-note scripts) runs gemma4. Keep aligned with llm_config._DEFAULT_MODEL.
DEFAULT_MODEL = "gemma4:e4b"
DEFAULT_TIMEOUT = 900  # seconds — bumped 2026-05-01 from 300 because the
# raised char-count target (5000-7000 chars) makes Gemma3 12B routinely take
# 6-12 min per article on the user's hardware. The 300s ceiling killed every
# generation in the 16:09 batch (0 articles produced, all read-timeout errors).


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
        # Restrict the Ollama endpoint to loopback/private hosts so a
        # tampered .env can't point the article pipeline at cloud
        # metadata endpoints (SSRF) or exfiltrate prompts to an
        # attacker-controlled server.
        from urllib.parse import urlparse as _urlparse
        _u = _urlparse(self.base_url)
        _safe_hosts = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
        if _u.scheme not in {"http", "https"} or (_u.hostname or "") not in _safe_hosts:
            raise ValueError(
                f"Refusing unsafe OLLAMA_API_URL={self.base_url!r}: "
                "only http(s)://localhost / 127.0.0.1 are allowed."
            )
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

        2026-05-11: on transient failure (connection / HTTP error /
        empty response), automatically falls back to the OpenAI
        Codex CLI (covered by the operator's existing OpenAI
        subscription — no metered API key billing). Disable with
        ``LLM_CODEX_FALLBACK=false`` to keep the original strict
        behaviour.

        Args:
            prompt: The input prompt.
            model: Override the default model for this call.
            temperature: Sampling temperature.

        Returns:
            The generated text.

        Raises:
            ConnectionError: If the server is unreachable AND Codex
                fallback is disabled OR also fails.
            RuntimeError: On a non-200 HTTP response when Codex
                fallback is disabled OR also fails.
        """
        model = model or self.default_model
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                # 2026-05-15 maintenance: Ollama default loads Gemma3:12b
                # at num_ctx=4096. Our Writer prompts run 2,500-3,500
                # chars (~2,500-3,500 tokens for Japanese) and target
                # 2,200-3,500 chars output → combined > 5,000 tokens
                # often exceeds 4,096. The single-article trace showed
                # actual Writer prompt = 11,900 chars (~8,925 tokens)
                # which OVERFLOWED the 8,192 setting — the title +
                # citation rules at prompt tail were getting silently
                # dropped, directly explaining today's Writer compliance
                # failures (citation block lost in truncation, タイトル
                # negative because title-section was at end of prompt).
                # Bump to 16,384 — gives ~12k token headroom for the
                # full prompt + 4k for the output. Costs ~+250MB VRAM
                # on Gemma3:12b Q4_K_M (verified safe on this host's
                # 12GB VRAM footprint).
                "num_ctx": 16384,
            },
            # Ollama unloads models after 5 minutes idle by default. With
            # the multiple-task pipeline (writer + scorer + maybe
            # regenerator), each article triggers 2-4 LLM calls spread
            # over several minutes — each reload costs ~20-30s for
            # Gemma3 12B. Keep models warm for 30 minutes between calls
            # so a full generate run doesn't pay the reload tax.
            "keep_alive": "30m",
        }

        logger.info(
            "Requesting generation (model=%s, prompt_len=%d).",
            model,
            len(prompt),
        )

        primary_exc: Exception | None = None
        text: str = ""
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            if resp.status_code != 200:
                logger.error(
                    "Ollama returned HTTP %d: %s",
                    resp.status_code, resp.text[:300],
                )
                primary_exc = RuntimeError(
                    f"Ollama API error (HTTP {resp.status_code})"
                )
            else:
                data = resp.json()
                text = data.get("response", "") or ""
                if not text.strip():
                    primary_exc = RuntimeError(
                        "Ollama returned empty response"
                    )
        except requests.exceptions.RequestException as exc:
            logger.error("Ollama request failed at %s: %s", self.base_url, exc)
            primary_exc = ConnectionError(
                f"Ollama request failed at {self.base_url}: {exc}"
            )

        if primary_exc is not None:
            fallback_text = self._codex_fallback(prompt)
            if fallback_text:
                logger.warning(
                    "Ollama failed (%s) — recovered via Codex CLI fallback (%d chars)",
                    primary_exc, len(fallback_text),
                )
                return fallback_text
            # No fallback or also failed — re-raise the original error
            # so existing callers' error-handling paths still trip.
            raise primary_exc

        logger.info("Generation complete (%d chars).", len(text))
        return text

    @staticmethod
    def _codex_fallback(prompt: str) -> str:
        """Invoke OpenAI Codex CLI as a fallback. Returns "" on any
        failure so the caller decides whether to error or continue.

        Cost: covered by the operator's OpenAI subscription (the CLI
        uses the subscription, NOT a metered API key). Disabled when
        ``LLM_CODEX_FALLBACK=false``.
        """
        if os.getenv("LLM_CODEX_FALLBACK", "true").lower() in (
            "false", "0", "no", "off",
        ):
            return ""
        codex_bin = os.getenv("CODEX_CLI_PATH") or "codex"
        # The prompt embeds scraped/LLM text, so bound its size and drop NULs
        # before handing it to the Codex CLI (defence against a feed trying to
        # smuggle an oversized / control-char payload into the fallback agent).
        safe_prompt = prompt.replace("\x00", "")[:16000]
        try:
            import subprocess
            # ``codex exec`` runs the CLI in headless mode with the
            # supplied prompt and returns the assistant text on stdout.
            # We add --sandbox read-only so the fallback cannot
            # accidentally modify files in this repo.
            r = subprocess.run(
                [codex_bin, "exec", "--sandbox", "read-only", safe_prompt],
                capture_output=True, text=True, timeout=900,
            )
            if r.returncode != 0:
                logger.warning(
                    "Codex fallback exited %d: %s",
                    r.returncode, (r.stderr or "")[:300],
                )
                return ""
            return (r.stdout or "").strip()
        except FileNotFoundError:
            logger.debug("Codex CLI not on PATH; fallback skipped")
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Codex fallback raised: %s", exc)
            return ""

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
