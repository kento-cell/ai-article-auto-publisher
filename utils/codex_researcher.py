"""Codex CLI-powered research pass for grounding local LLM generation.

Gemma3 cannot browse the web and hallucinates store URLs, addresses,
and official-site links. Codex CLI (GPT-5.4) *can* browse the web via
its built-in web_search tool, so this module delegates the factual
research step to Codex and returns a structured brief that Gemma3 can
cite from.

Workflow
--------
1. :meth:`CodexResearcher.research` takes a source post (title +
   content) and an optional area hint.
2. It invokes ``codex exec --sandbox read-only --full-auto`` with a
   carefully scoped prompt that asks Codex to web-search for every
   store/place mentioned in the source, and to return a single JSON
   object with verified facts.
3. The JSON block is extracted from Codex's free-form output and
   returned as a :class:`ResearchBrief` ready for prompt injection.

The Codex CLI is expected on ``PATH`` (Windows: usually at
``%AppData%/Roaming/npm/codex``). When it is not available, the
researcher degrades gracefully: :meth:`research` returns an empty
brief and logs a warning, so the pipeline keeps running with the
unchanged Gemma3-only behaviour.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Max seconds a single Codex research call may take. Web search pushes
# Codex well past the default 60s; keep a generous ceiling.
_CODEX_TIMEOUT_SECONDS = 240

# Regex that grabs the last balanced JSON object in Codex's stdout.
_JSON_BLOCK_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


@dataclass
class StoreFact:
    """One verified entity from the Codex research pass."""

    name: str
    verified: bool = False
    url: str = ""
    address: str = ""
    source: str = ""
    note: str = ""


@dataclass
class ResearchBrief:
    """Structured research output passed to the article generator.

    Attributes:
        stores: List of :class:`StoreFact` entries Codex verified.
        summary: Free-text one-paragraph summary Codex produced about
            the source post, grounded in web results.
        raw_output: Entire Codex stdout, kept for debugging / audit.
    """

    stores: list[StoreFact] = field(default_factory=list)
    summary: str = ""
    raw_output: str = ""

    def to_prompt_block(self) -> str:
        """Render the brief as a Markdown snippet for prompt injection.

        The format is deliberately machine-tag-like so the downstream
        LLM knows the block is authoritative fact and prose elsewhere
        is colour. Each store is given a short bullet list so Gemma3
        can lift individual fields without inventing new ones.
        """
        if not self.stores and not self.summary:
            return ""

        lines: list[str] = [
            "【検証済みファクトブリーフ — Codex Web検索結果】",
            "以下の情報は事前にWeb検索で裏付け済みです。",
            "**記事本文で言及できる店舗・URLはこの中に登場するもののみ**。",
            "このブリーフに無い店名・URL・住所を自分で補完してはいけません。",
            "",
        ]
        if self.summary:
            lines.append("## 概況")
            lines.append(self.summary.strip())
            lines.append("")

        if self.stores:
            lines.append("## 検証済みスポット")
            for idx, store in enumerate(self.stores, start=1):
                status = "✅実在確認" if store.verified else "❓未確認（使用禁止）"
                lines.append(f"{idx}. **{store.name}** — {status}")
                if store.address:
                    lines.append(f"   - 住所: {store.address}")
                if store.url:
                    lines.append(f"   - 公式: {store.url}")
                if store.source:
                    lines.append(f"   - 出典: {store.source}")
                if store.note:
                    lines.append(f"   - メモ: {store.note}")
            lines.append("")

        lines.append(
            "上記以外の店名・URL・住所は捏造扱いとし記事に一切書かないこと。"
        )
        return "\n".join(lines)


class CodexResearcher:
    """Run a Codex research pass for a given source article.

    Args:
        codex_path: Optional explicit path to the Codex executable.
            Falls back to ``shutil.which('codex')``.
        timeout_seconds: Override the default subprocess timeout.
        enabled: Master switch — when False, :meth:`research` is a
            no-op. Useful for unit tests or for disabling the feature
            from config without tearing down the wiring.
    """

    def __init__(
        self,
        codex_path: str | None = None,
        timeout_seconds: int = _CODEX_TIMEOUT_SECONDS,
        enabled: bool = True,
    ) -> None:
        self.codex_path = codex_path or shutil.which("codex")
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled

    def is_available(self) -> bool:
        """Return True when a usable Codex executable is configured."""
        return bool(self.enabled and self.codex_path)

    def research(
        self,
        source_title: str,
        source_content: str,
        area_hint: str = "",
    ) -> ResearchBrief:
        """Run one Codex research pass and return a structured brief.

        Args:
            source_title: The original post title (Bluesky / RSS).
            source_content: The original post body text.
            area_hint: Optional locality keyword (e.g. ``"下北沢"``)
                biasing Codex toward the right geography.

        Returns:
            :class:`ResearchBrief` — empty when Codex is unavailable or
            returns unparseable output.
        """
        brief = ResearchBrief()
        if not self.is_available():
            logger.info(
                "Codex researcher disabled or unavailable — skipping"
            )
            return brief

        prompt = self._build_prompt(source_title, source_content, area_hint)
        try:
            completed = subprocess.run(
                [
                    self.codex_path or "codex",
                    "exec",
                    "--sandbox",
                    "read-only",
                    "--full-auto",
                    "-",  # read prompt from stdin (avoids Windows argv limits
                          # and the quirky argv escaping that was dropping the
                          # post body before Codex could read it)
                ],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Codex research timed out after %ds", self.timeout_seconds)
            return brief
        except FileNotFoundError:
            logger.warning("Codex CLI not found at %s", self.codex_path)
            return brief
        except Exception as exc:
            logger.warning("Codex research failed: %s", exc)
            return brief

        brief.raw_output = completed.stdout or ""
        if completed.returncode != 0:
            logger.warning(
                "Codex exited %d: %s",
                completed.returncode,
                (completed.stderr or "")[:200],
            )
            return brief

        parsed = self._extract_json(brief.raw_output)
        if parsed is None:
            logger.warning("Could not parse JSON brief from Codex output")
            return brief

        brief.summary = str(parsed.get("summary", "")).strip()
        for raw in parsed.get("stores", []) or []:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            brief.stores.append(
                StoreFact(
                    name=name,
                    verified=bool(raw.get("verified", False)),
                    url=str(raw.get("url", "")).strip(),
                    address=str(raw.get("address", "")).strip(),
                    source=str(raw.get("source", "")).strip(),
                    note=str(raw.get("note", "")).strip(),
                )
            )
        logger.info(
            "Codex brief: %d stores (%d verified), summary=%dchars",
            len(brief.stores),
            sum(1 for s in brief.stores if s.verified),
            len(brief.summary),
        )
        return brief

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        title: str,
        content: str,
        area_hint: str,
    ) -> str:
        """Return the single-shot research prompt given to Codex."""
        # Trim overly long source content — Codex does not need every
        # byte and shorter prompts mean faster runs.
        safe_content = (content or "")[:1500]
        hint_line = (
            f"\n- エリアヒント: {area_hint} — この地域で実在する店のみ扱うこと。"
            if area_hint else ""
        )
        parts: list[str] = [
            "あなたはリサーチエージェントです。以下の日本語SNS投稿について、",
            "Web検索で登場する店名・施設名を全て調査し、実在する場合のみ",
            "正確な情報を集めてください。",
            "\n\n【絶対ルール】",
            "\n- Web検索結果に無い店は verified=false にして url/address を空にする。",
            "\n- 食べログなど未確認な二次情報のみの場合も verified=false 扱い。",
            "\n- 検索で見つからない店を『存在するはず』と推測してはいけません。",
            "\n- 店舗公式サイトがあればそれを url に入れる。無ければ Google Maps URL でよい。",
            "\n- 全て日本語で返すこと。",
            hint_line,
            "\n\n【出力形式 — JSON 1件のみ、前後に説明文不要】",
            '\n{"stores":[{"name":"...","verified":true,"url":"...",',
            '"address":"...","source":"...","note":"..."}],',
            '"summary":"..."}',
            "\n\n【投稿タイトル】\n",
            title,
            "\n\n【投稿本文】\n",
            safe_content,
        ]
        return "".join(parts)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Pull the most plausible JSON object out of Codex's stdout.

        Codex emits reasoning + tool logs around the final answer, so
        we scan for JSON blocks and try to parse the **last** one that
        looks like our schema (contains ``stores`` or ``summary``).
        """
        if not text:
            return None
        candidates = _JSON_BLOCK_RE.findall(text)
        for candidate in reversed(candidates):
            try:
                obj = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and ("stores" in obj or "summary" in obj):
                return obj
        return None
