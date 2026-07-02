"""Dry-run: exercise chatgpt_image_batch with USE_GEMINI_IMAGES=1 to
prove the full batch path (cover + inline_count=2) yields real PNGs
under data/images/covers/ and _LAST_BATCH_META.backend='gemini'.

Not a real article publish — just validates the batch helper with the
Gemini backend end to end. If this passes we can flip Gemini on in the
next real /routine.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for ln in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemini_batch_dryrun")

from generators.chatgpt_batch_helper import (
    chatgpt_image_batch,
    get_last_batch_meta,
    is_chatgpt_image_gen_enabled,
    is_gemini_image_gen_enabled,
)

TITLE = "【朝メモ】観葉植物入門 3種 (ガジュマル / サンスベリア / ポトス) — 光量・水やり・鉢サイズを実測比較"
CONTENT = """観葉植物初心者に本当に育てやすい 3 品種を、光量ルクス値・水やり頻度・
培養土・鉢サイズで並列比較します。

## 品種1: ガジュマル

沖縄由来の樹木。 直射日光 20,000 lux で葉焼けせず、 週 1 回の水やりで十分。

## 品種2: サンスベリア ゼラニカ

耐陰性最強。 500 lux (暗い北向き部屋) でも枯れず、 冬季は月 1 回の水やり。

## 品種3: ポトス ゴールデン

垂れ下がる葉が映える。 明るい日陰 5,000 lux、 春夏は週 2 回水やり。
"""


def main() -> int:
    log.info(
        "flags: USE_CHATGPT_IMAGES=%s USE_GEMINI_IMAGES=%s",
        is_chatgpt_image_gen_enabled(), is_gemini_image_gen_enabled(),
    )
    if not is_gemini_image_gen_enabled():
        log.error("USE_GEMINI_IMAGES is not set — dry-run has nothing to prove")
        return 1

    cover, inlines = chatgpt_image_batch(
        title=TITLE,
        content=CONTENT,
        inline_count=2,
        slug_hint="gemini_dryrun_kanyou",
        genre_hint="lifestyle / interior plants",
    )
    meta = get_last_batch_meta()
    log.info("=== RESULT ===")
    log.info("backend meta: %s", meta)
    log.info("cover: %s", cover)
    for i, p in enumerate(inlines):
        log.info("inline[%d]: %s", i, p)

    ok = (
        meta is not None
        and meta.get("backend") == "gemini"
        and cover is not None
        and cover.exists()
        and cover.stat().st_size > 50_000
    )
    if not ok:
        log.error("FAIL: expected gemini backend + valid cover, got: %s", meta)
        return 2
    log.info("PASS: %d bytes cover + %d inline via Gemini",
             cover.stat().st_size, len(inlines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
