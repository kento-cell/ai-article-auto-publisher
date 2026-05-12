"""Regenerate ONE inline image for the akabane article (slot 0-3).

Used after a batch run produced one stylistic outlier — calls
ChatGPTImageGenerator.generate_batch with a single prompt so the
slot can be re-rolled without burning quota on the other 3 images.

Usage: py scripts/regen_akabane_single_inline.py [SLOT]
       SLOT is 0..3 (0 = 1軒目 まるます家). Default: 0.

Brave must be CLOSED before running.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("regen_akabane_single_inline")

TITLE = "赤羽せんべろ4軒 - 戦後闇市から続く立ち飲み・もつ焼き・うなぎの聖地"
GENRE = "日本のローカル酒場 / 居酒屋 / もつ焼き / うなぎ / 立ち飲み"
DRAFT = _REPO / "data" / "articles" / "_drafts" / "akabane_gourmet_20260511.md"


def _extract_h2_sections(content: str) -> list[tuple[str, str]]:
    h2_pat = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(h2_pat.finditer(content))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        title_text = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end]
        body = re.sub(r"```[\s\S]*?```", "", body)
        body = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body)
        body = re.sub(r"^>.*$", "", body, flags=re.MULTILINE)
        body = re.sub(r"\s+", " ", body).strip()
        out.append((title_text, body[:220]))
    return out


def main() -> int:
    slot = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if slot < 0 or slot > 3:
        logger.error("slot must be 0..3, got %d", slot)
        return 1

    content = DRAFT.read_text(encoding="utf-8")

    from generators.chatgpt_batch_helper import _select_image_sections
    from generators.visual_prompt_builder import build_visual_prompt
    from generators.chatgpt_image_generator import ChatGPTImageGenerator

    selected = _select_image_sections(_extract_h2_sections(content), 4)
    h_title, _ = selected[slot]
    logger.info("Regenerating slot %d: %s", slot, h_title)

    prompt = build_visual_prompt(TITLE, section=h_title, genre_hint=GENRE)

    out_dir = _REPO / "data" / "images" / "covers"
    _now = time.time()
    uniq = (
        f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(_now))}"
        f"_{int((_now % 1) * 1_000_000):06d}_{os.getpid()}"
    )
    out_path = out_dir / (
        f"chatgpt_akabane_single_{uniq}_inline_{slot:02d}_retry.png"
    )

    gen = ChatGPTImageGenerator(headless=False)
    results = gen.generate_batch(
        prompts=[prompt],
        size="landscape",
        out_paths=[out_path],
        topic=TITLE,
        style_block=None,
    )

    print("\n=== RESULT ===")
    print(f"slot {slot} ({h_title})")
    print(f"  -> {results[0] if results[0] else 'FAILED'}")
    return 0 if results[0] else 4


if __name__ == "__main__":
    raise SystemExit(main())
