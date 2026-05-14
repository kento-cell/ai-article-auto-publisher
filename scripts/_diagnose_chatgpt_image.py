"""Diagnose why ChatGPT image gen returns 23618-byte note-logo PNGs.

Plan: run a single image gen with extra logging, then inspect:
- The img URL returned by _wait_for_image
- The HTTP response (size, content-type)
- The actual saved file bytes (first 32 bytes — PNG signature?)
- A page screenshot at gen time
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Disable vision-eval and CDP so we get a clean repro
os.environ["CHATGPT_VISION_EVAL"] = "0"
os.environ["CHATGPT_CDP_PORT"] = ""

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

import subprocess, time
subprocess.run(["taskkill", "/F", "/IM", "brave.exe"], check=False, capture_output=True)
time.sleep(2)

from generators.chatgpt_image_generator import ChatGPTImageGenerator

gen = ChatGPTImageGenerator()
out = gen.generate(
    prompt=(
        "A bold infographic-style illustration showing 'Cisco $5.3B AI orders' "
        "and 'minus 4,000 jobs' as opposing arrows on a corporate chart, "
        "yellow and dark navy palette, magazine editorial style"
    ),
    size="square",
    out_path=Path("data/images/covers/diag_test_cover.png"),
)
print(f"\nRESULT: {out}")
if out and out.exists():
    print(f"file size: {out.stat().st_size} bytes")
    with open(out, "rb") as f:
        head = f.read(16)
    print(f"first 16 bytes hex: {head.hex()}")
    print(f"is PNG?: {head[:8].hex() == '89504e470d0a1a0a'}")
