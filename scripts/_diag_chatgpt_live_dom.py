"""Live DOM capture for the ChatGPT image selector.

Runs the REAL generation flow (open browser via CDP, send the prompt)
but replaces `_wait_for_image` with a poller that, the instant ANY
<img> appears, dumps the full DOM facts for every image on the page so
we can see exactly which `_wait_for_image` filter rejects the real
generated image.

Brave CDP only. New tab only. No posting.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
env = _REPO / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

_PROBE = r"""() => {
    const imgs = Array.from(document.querySelectorAll('img'));
    return {
        roles: document.querySelectorAll('[data-message-author-role]').length,
        assistant: document.querySelectorAll(
            '[data-message-author-role="assistant"]').length,
        turns: document.querySelectorAll(
            '[data-testid^="conversation-turn"]').length,
        articles: document.querySelectorAll('article').length,
        rows: imgs.map(img => ({
            src: img.src || '',
            nW: img.naturalWidth, nH: img.naturalHeight,
            w: img.width, h: img.height,
            alt: img.alt || '',
            inAssistant: !!img.closest(
                '[data-message-author-role="assistant"]'),
            inNav: !!img.closest('nav'),
            inArticle: !!img.closest('article'),
            inTurn: !!img.closest('[data-testid^="conversation-turn"]'),
        })),
    };
}"""


def main() -> int:
    from generators.chatgpt_image_generator import ChatGPTImageGenerator

    gen = ChatGPTImageGenerator(headless=False)
    prompt = (
        "A bold infographic-style cover illustration: a friendly robot "
        "character holding a glowing shield, big bold Japanese-style title "
        "space at top, dark navy background with cyan accents, flat vector art."
    )
    full = gen._build_prompt(prompt, "landscape")
    try:
        gen._open_browser()
        page = gen._page
        gen._send_prompt(full)
        print("prompt sent — polling for images (up to 280s)...")
        deadline = time.time() + 280
        dumped = False
        while time.time() < deadline:
            try:
                data = page.evaluate(_PROBE)
            except Exception as exc:  # noqa: BLE001
                print(f"evaluate err: {exc}")
                time.sleep(2)
                continue
            # Trigger ONLY on an image inside a conversation turn that is
            # NOT in the sidebar nav — i.e. a genuine generated image.
            big = [r for r in data["rows"]
                   if (r["nW"] or r["w"] or 0) >= 400
                   and r["inTurn"] and not r["inNav"]]
            if big and not dumped:
                print(f"\n=== IMAGE APPEARED ({time.strftime('%H:%M:%S')}) ===")
                print(f"role-attr els: {data['roles']}  "
                      f"assistant: {data['assistant']}  "
                      f"conversation-turn: {data['turns']}  "
                      f"article: {data['articles']}")
                for i, r in enumerate(data["rows"]):
                    print(f"\n[{i}] {r['src']}")
                    print(f"    natural={r['nW']}x{r['nH']} attr={r['w']}x{r['h']}")
                    print(f"    alt={r['alt'][:60]!r}")
                    print(f"    inAssistant={r['inAssistant']} "
                          f"inNav={r['inNav']} inArticle={r['inArticle']} "
                          f"inTurn={r['inTurn']}")
                # keep watching a bit so naturalWidth settles
                dumped = True
                t2 = time.time() + 25
                while time.time() < t2:
                    time.sleep(5)
                    try:
                        d2 = page.evaluate(_PROBE)
                    except Exception:  # noqa: BLE001
                        continue
                    print(f"\n  ...resnap @ {time.strftime('%H:%M:%S')}:")
                    for i, r in enumerate(d2["rows"]):
                        if (r["nW"] or r["w"] or 0) >= 400:
                            print(f"    [{i}] {r['nW']}x{r['nH']} "
                                  f"inAssistant={r['inAssistant']} "
                                  f"inTurn={r['inTurn']} {r['src'][:90]}")
                break
            time.sleep(3)
        if not dumped:
            print("no >=400px image appeared within window")
    finally:
        try:
            gen._close_browser()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
