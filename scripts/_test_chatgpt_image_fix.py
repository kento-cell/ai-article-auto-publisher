"""Single-image smoke test for the 2026-05-15 ChatGPT image selector fix.

Generates ONE image via the real ChatGPT Web UI (Brave CDP) and verifies
the downloaded file is a real generation (>51,200 bytes) rather than the
23,618-byte note-logo placeholder that the old `document` fallback caught.

Run:  py scripts/_test_chatgpt_image_fix.py
Exit: 0 = real image, 1 = still placeholder / failed.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("test")


def main() -> int:
    from generators.chatgpt_image_generator import ChatGPTImageGenerator

    out = _REPO / "data" / "_test_chatgpt_fix.png"
    if out.exists():
        out.unlink()

    gen = ChatGPTImageGenerator(headless=False)
    prompt = (
        "A bold infographic-style cover illustration: a friendly robot "
        "character holding a glowing shield, big bold Japanese-style title "
        "space at top, dark navy background with cyan accents, flat vector art."
    )
    try:
        result = gen.generate(prompt, size="landscape", out_path=out)
    except Exception as exc:  # noqa: BLE001
        log.error("generate raised: %s", exc)
        return 1
    finally:
        try:
            gen.close()
        except Exception:
            pass

    if result is None or not out.exists():
        log.error("FAIL — no image produced")
        return 1
    size = out.stat().st_size
    log.info("downloaded %d bytes -> %s", size, out)
    if size == 23618:
        log.error("FAIL — still the 23,618-byte note-logo placeholder")
        return 1
    if size < 51200:
        log.error("FAIL — %d bytes < 51,200 (suspicious, likely placeholder)", size)
        return 1
    log.info("PASS — real ChatGPT image (%d bytes)", size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
