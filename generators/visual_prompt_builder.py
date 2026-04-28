"""Article → image-generation prompt converter.

Takes an article title (and optionally an H2 section heading) plus
a topic hint, asks the local LLM (Gemma3 by default) to produce a
visual description suitable for ChatGPT's gpt-image-1.5 backend.

Why we don't just feed the raw title:

* Article titles in this pipeline are aggressive ad-copy
  (【完全】99%が知らない…) — feeding them as-is biases the
  image generator toward UI mockups, sales-style infographics, or
  text-laden visuals.
* What we want is the *underlying topic* expressed as a short visual
  brief: subject, palette, composition, mood, with explicit negative
  constraints (no text, no logos, no UI screenshots).
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Style/format guard appended to every Japanese summary so ChatGPT
# always knows it's drawing a Ghibli-style scene of the article's
# subject. Kept brief — chatgpt_image_generator wraps its own
# detailed style block around this anyway.
_NEG_CONSTRAINTS: str = ""  # the heavy lifting moved into the wrapper.

_PROMPT_FOR_LLM: str = """\
あなたは記事のサムネイル画像のビジュアルディレクターです。
以下の記事タイトル・セクション・ジャンルから、ChatGPT画像生成に渡す
**日本語の記事要約 (2〜3文、150字以内)** を作成してください。

記事タイトル: {title}
{section_block}
ジャンル傾向: {genre_hint}

要件:
- **日本語で2〜3文、合計150字以内**
- 「この記事は〜について」のような客観的な要約から始め、
  続いて「画像にはこんなシーンを描いてほしい」を添える
- 描いてほしいシーンは水彩アニメ調 (宮崎駿、新海誠、細田守調) で
  絵にしやすい題材を選ぶ
  (例: 工房で光るデータを操る少年、本に囲まれた机、
   森の中の機械、暖炉の前で瓶を覗き込む小さな精霊 等)
- 抽象的なメタファーは避け、絵に起こせる具体的なシーンを書く
- 「Generate」「prompt」等の英語指示語は混ぜない
- 引用符・前置き・後置きは禁止

良い例:
「ChatGPTで画像を自動生成するパイプラインを解説する技術記事です。神秘的な工房で、本と機械に囲まれた少年が、空中を流れる光のデータの川をやさしく見つめているシーンを描いてください。」

悪い例:
"A small character watching data streams" ← 英語禁止
「ニューラルネットの図」 ← 抽象すぎる
「侍が刀を抜く」 ← 中世ファンタジーNG

出力: 上記日本語要約のみ。前置き・後置き・引用符・改行は禁止。
"""


def build_visual_prompt(
    title: str,
    section: str | None = None,
    genre_hint: str = "general tech / lifestyle",
    *,
    llm_generate: Callable[[str], str] | None = None,
) -> str:
    """Return a single-line English visual brief for ChatGPT image gen.

    Args:
        title: Article title.
        section: Optional H2 heading for inline images. ``None`` for
            cover image (whole-article visual).
        genre_hint: Short hint of the article genre (e.g.
            ``"AI / agents"``, ``"K-beauty / skincare"``). Helps the
            LLM choose palette & subject.
        llm_generate: Callable that takes a prompt and returns the
            LLM's response. Defaults to ``LocalLLM().generate``.
    """
    if llm_generate is None:
        # Lazy import — keeps this module cheap to import.
        from generators.llm_config import get_llm
        llm = get_llm("writer")
        llm_generate = llm.generate

    section_block = f"対象セクション: {section}\n" if section else ""
    prompt = _PROMPT_FOR_LLM.format(
        title=title,
        section_block=section_block,
        genre_hint=genre_hint,
    )

    try:
        raw = llm_generate(prompt).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "visual_prompt_builder: LLM call failed (%s); using fallback.",
            exc,
        )
        raw = _fallback_prompt(title, section)

    # The LLM sometimes wraps in quotes or "Prompt:" prefixes — strip them.
    cleaned = raw.strip().strip('"').strip("'")
    for prefix in ("Prompt:", "prompt:", "Visual prompt:", "ビジュアルプロンプト:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    # Drop trailing blocks if the model gave multi-line output.
    cleaned = cleaned.splitlines()[0].strip() if cleaned else ""
    if not cleaned:
        cleaned = _fallback_prompt(title, section)

    return cleaned + _NEG_CONSTRAINTS


def _fallback_prompt(title: str, section: str | None) -> str:
    """Used when the LLM is unavailable. Generic but safe (Japanese)."""
    if section:
        return (
            f"この記事のセクション「{section}」のためのインライン画像を作ります。"
            f"温かい光に包まれた小さな工房で、テーマを象徴する物が"
            f"優しく浮かんでいるシーンを描いてください。"
        )
    return (
        f"この記事「{title}」のサムネイル画像を作ります。"
        f"暖色の光が差し込む静かな部屋で、本と機械に囲まれた"
        f"小さなキャラクターがテーマを見つめているシーンを描いてください。"
    )
