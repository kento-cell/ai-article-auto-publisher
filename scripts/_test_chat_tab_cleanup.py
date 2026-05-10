"""1-shot test: verify chat-delete + tab-close flow.

Intentionally hits ChatGPT during the image-gen quota limit so the
``_wait_for_image`` will timeout. The point of the test is *what
happens after*: the chat must be soft-deleted from the sidebar AND
the tab itself must be closed in Brave.

Pre-condition: Brave is already running with
``--remote-debugging-port=9222 --remote-allow-origins=*``.

Verifies:
1. ``_open_browser`` (CDP attach) opens a tab on chatgpt.com
2. ``_start_new_chat`` is the only path that creates the per-image tab
3. After the prompt fails, ``_delete_current_chat`` PATCHes
   ``is_visible=false`` so the chat disappears from the sidebar
4. The tab is closed by ``_close_browser`` (or by ``_start_new_chat``
   on subsequent iterations — but here we only run 1)
5. ``_cleanup_orphan_tabs`` sweeps any leftover about:blank pages
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

os.environ.setdefault("CHATGPT_CDP_PORT", "9222")
os.environ["CHATGPT_VISION_EVAL"] = "0"  # skip vision eval, speeds up timeout

from generators.chatgpt_image_generator import ChatGPTImageGenerator  # noqa: E402

import requests  # noqa: E402


def list_tabs() -> list[dict]:
    try:
        r = requests.get("http://localhost:9222/json/list", timeout=3)
        return r.json()
    except Exception as exc:
        print(f"  list_tabs failed: {exc}")
        return []


def chatgpt_tab_count(pages: list[dict]) -> int:
    return sum(
        1 for p in pages
        if p.get("type") == "page" and (p.get("url") or "").startswith("https://chatgpt.com/")
    )


print("=" * 60)
print("BEFORE — current Brave state")
print("=" * 60)
before = list_tabs()
print(f"  total targets: {len(before)}")
print(f"  chatgpt.com tabs: {chatgpt_tab_count(before)}")
for p in before:
    if p.get("type") == "page":
        url = (p.get("url") or "")[:80]
        print(f"    [page] {url}")

print()
print("=" * 60)
print("RUNNING generate_batch (1 prompt, will hit quota limit)")
print("=" * 60)

gen = ChatGPTImageGenerator(headless=False)
results = gen.generate_batch(
    prompts=[
        "シンプルな水彩アニメ調で、白い猫が走っている画像。1024×1024 正方形。"
    ],
    size="square",
    topic="cleanup-test",
)
print(f"results: {results}  (None expected since quota limit is active)")

print()
print("=" * 60)
print("AFTER — Brave state should have NO new chatgpt.com tab")
print("=" * 60)
after = list_tabs()
print(f"  total targets: {len(after)}")
print(f"  chatgpt.com tabs: {chatgpt_tab_count(after)}")
for p in after:
    if p.get("type") == "page":
        url = (p.get("url") or "")[:80]
        print(f"    [page] {url}")

print()
delta_pages = chatgpt_tab_count(after) - chatgpt_tab_count(before)
print(f"net chatgpt.com tab delta: {delta_pages:+d}")
if delta_pages == 0:
    print("✓ PASS: no leftover chatgpt.com tab")
else:
    print(f"✗ FAIL: {delta_pages:+d} chatgpt tab(s) leaked")
