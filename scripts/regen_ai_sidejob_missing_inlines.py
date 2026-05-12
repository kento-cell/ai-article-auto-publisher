"""Retry the 2 timed-out inline images (Week 3, Week 4) for the AI
sidejob roadmap article. Brave must be CLOSED.

Usage: py scripts/regen_ai_sidejob_missing_inlines.py [SLOT...]
       SLOT defaults to "2 3" (Week 3 + Week 4).
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
logger = logging.getLogger("regen_ai_sidejob_missing_inlines")

TITLE = (
    "【2026-05実証データ版】AI副業30日ロードマップ — "
    "月¥175,634クリエイターの公開実績から逆算した月¥5万達成の最短ルート"
)
GENRE = "AI副業 / 個人マネタイズ / ChatGPT / Claude / 自動化 / 副業ロードマップ"
DRAFT = _REPO / "data" / "articles" / "_drafts" / "ai_sidejob_30day_roadmap_20260512.md"


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
    slots = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [2, 3]
    if not all(0 <= s <= 3 for s in slots):
        logger.error("slots must be in 0..3, got %s", slots)
        return 1

    content = DRAFT.read_text(encoding="utf-8")

    from generators.chatgpt_batch_helper import _select_image_sections
    from generators.visual_prompt_builder import build_visual_prompt
    from generators.chatgpt_image_generator import ChatGPTImageGenerator

    selected = _select_image_sections(_extract_h2_sections(content), 4)

    out_dir = _REPO / "data" / "images" / "covers"
    _now = time.time()
    uniq = (
        f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(_now))}"
        f"_{int((_now % 1) * 1_000_000):06d}_{os.getpid()}"
    )

    prompts: list[str] = []
    out_paths: list[Path] = []
    for slot in slots:
        h_title, _ = selected[slot]
        logger.info("Regenerating slot %d: %s", slot, h_title)
        prompts.append(build_visual_prompt(TITLE, section=h_title, genre_hint=GENRE))
        out_paths.append(
            out_dir / f"chatgpt_ai_sidejob_retry_{uniq}_inline_{slot:02d}_retry.png"
        )

    gen = ChatGPTImageGenerator(headless=False)
    results = gen.generate_batch(
        prompts=prompts,
        size="landscape",
        out_paths=out_paths,
        topic=TITLE,
        style_block=None,
    )

    print("\n=== RESULT ===")
    for slot, p in zip(slots, results):
        h_title, _ = selected[slot]
        status = str(p) if p else "FAILED"
        print(f"  slot {slot} ({h_title})")
        print(f"    -> {status}")
    n_ok = sum(1 for p in results if p)
    return 0 if n_ok == len(slots) else 4


if __name__ == "__main__":
    raise SystemExit(main())
