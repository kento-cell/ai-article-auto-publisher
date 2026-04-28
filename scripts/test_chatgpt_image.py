"""Smoke-test the ChatGPT image generator.

Generates one cover image with a fixed prompt, headed (visible) so you
can see what's happening. Saves to data/images/covers/.

Usage::

    py scripts/test_chatgpt_image.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from generators.chatgpt_image_generator import ChatGPTImageGenerator


def main() -> int:
    gen = ChatGPTImageGenerator(headless=False)
    out = gen.generate(
        prompt=(
            "A modern editorial-style thumbnail for an AI tech article "
            "about GPT-5.5. Clean composition, deep blue and purple "
            "gradient background, abstract neural network nodes, no text."
        ),
        size="landscape",
    )
    if out:
        print(f"OK: {out}")
        return 0
    print("FAIL: no image returned")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
