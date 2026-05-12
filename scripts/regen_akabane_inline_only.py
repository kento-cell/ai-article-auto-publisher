"""Regenerate ONLY the inline images for the akabane gourmet article.

Reuses the existing cover (which the user has approved) and routes
the 4 inline slots to the 4 shop sections via the new section-priority
logic. Brave must be CLOSED before running.
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
logger = logging.getLogger("regen_akabane_inline_only")

TITLE = "赤羽せんべろ4軒 - 戦後闇市から続く立ち飲み・もつ焼き・うなぎの聖地"
GENRE = "日本のローカル酒場 / 居酒屋 / もつ焼き / うなぎ / 立ち飲み"
DRAFT = _REPO / "data" / "articles" / "_drafts" / "akabane_gourmet_20260511.md"
INLINE_COUNT = 4


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
    if not DRAFT.exists():
        logger.error("draft not found: %s", DRAFT)
        return 2
    content = DRAFT.read_text(encoding="utf-8")

    from generators.chatgpt_batch_helper import _select_image_sections
    from generators.visual_prompt_builder import build_visual_prompt
    from generators.chatgpt_image_generator import ChatGPTImageGenerator

    all_h2 = _extract_h2_sections(content)
    selected = _select_image_sections(all_h2, INLINE_COUNT)
    logger.info("Selected %d sections for inline images:", len(selected))
    for i, (h_title, _) in enumerate(selected, 1):
        logger.info("  [%d] %s", i, h_title)

    prompts = [
        build_visual_prompt(TITLE, section=h_title, genre_hint=GENRE)
        for h_title, _ in selected
    ]

    out_dir = _REPO / "data" / "images" / "covers"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "akabane_inline_regen"
    _now = time.time()
    uniq = (
        f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(_now))}"
        f"_{int((_now % 1) * 1_000_000):06d}_{os.getpid()}"
    )
    out_paths = [
        out_dir / f"chatgpt_{safe}_{uniq}_inline_{i:02d}.png"
        for i in range(INLINE_COUNT)
    ]

    logger.info("Calling ChatGPT image gen (%d inline images, ~%d sec)…",
                INLINE_COUNT, INLINE_COUNT * 90)
    gen = ChatGPTImageGenerator(headless=False)
    results = gen.generate_batch(
        prompts=prompts,
        size="landscape",
        out_paths=out_paths,
        topic=TITLE,
        style_block=None,  # ghibli default
    )

    print("\n=== RESULT ===")
    for i, p in enumerate(results, 1):
        status = str(p) if p else "FAILED"
        print(f"  [{i}] {selected[i - 1][0]}\n      -> {status}")
    n_ok = sum(1 for p in results if p)
    return 0 if n_ok == INLINE_COUNT else 4


if __name__ == "__main__":
    raise SystemExit(main())
