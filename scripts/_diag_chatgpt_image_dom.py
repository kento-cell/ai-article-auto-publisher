"""Read-only CDP DOM inspector for the generated ChatGPT image.

Attaches to the already-running Brave (CHATGPT_CDP_PORT, default 9222),
finds the EXISTING tab that is already on chatgpt.com (does NOT open a
fresh tab — the generated image lives in the chat that just timed out),
and dumps, for every <img> on the page:

  * full src
  * naturalWidth/Height + width/height
  * whether it has a [data-message-author-role="assistant"] ancestor
  * whether it has a <nav> ancestor
  * whether the FIXED _wait_for_image filters would keep it, and which
    individual filter (assistant-turn / nav / size / token / gizmo_id)
    rejects it.

Does NOT send a prompt, does NOT post, does NOT close the user's tab.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent

# Load .env so CHATGPT_CDP_PORT is honoured.
env = _REPO / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_PROBE = r"""() => {
    const imgs = Array.from(document.querySelectorAll('img'));
    const turns = document.querySelectorAll(
        '[data-message-author-role="assistant"]');
    // Also probe alternative author-role attribute spellings.
    const altRole = {
        'data-message-author-role': document.querySelectorAll(
            '[data-message-author-role]').length,
        'assistant-turns': turns.length,
        'data-testid-conversation-turn': document.querySelectorAll(
            '[data-testid^="conversation-turn"]').length,
        'article': document.querySelectorAll('article').length,
    };
    const rows = imgs.map(img => {
        const inAssistant = !!img.closest(
            '[data-message-author-role="assistant"]');
        const inNav = !!img.closest('nav');
        const inArticle = !!img.closest('article');
        const inTurn = !!img.closest('[data-testid^="conversation-turn"]');
        return {
            src: img.src || '',
            nW: img.naturalWidth, nH: img.naturalHeight,
            w: img.width, h: img.height,
            alt: img.alt || '',
            inAssistant, inNav, inArticle, inTurn,
            tag: img.tagName,
        };
    });
    return { altRole, rows };
}"""


def classify(r: dict) -> str:
    """Why would the FIXED selector reject this img?"""
    reasons = []
    if not r["inAssistant"]:
        reasons.append("NOT-in-assistant-turn")
    if r["inNav"]:
        reasons.append("in-nav")
    w = r["nW"] or r["w"] or 0
    h = r["nH"] or r["h"] or 0
    if w < 200 or h < 200:
        reasons.append(f"size<200 ({w}x{h})")
    src = r["src"]
    if not (src.startswith("https://") or src.startswith("blob:")):
        reasons.append("bad-scheme")
    import re
    if re.search(r"avatar|sprite|emoji|icon", src):
        reasons.append("token-blocklist")
    if re.search(r"[?&]gizmo_id=", src):
        reasons.append("gizmo_id")
    return "KEEP" if not reasons else " | ".join(reasons)


def main() -> int:
    port = os.environ.get("CHATGPT_CDP_PORT", "9222")
    cdp_url = f"http://localhost:{port}"
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: cannot CDP-attach to {cdp_url}: {exc}")
        pw.stop()
        return 1

    if not browser.contexts:
        print("FATAL: CDP browser exposed no contexts")
        browser.close()
        pw.stop()
        return 1
    ctx = browser.contexts[0]
    print(f"attached: {cdp_url} | {len(ctx.pages)} existing tab(s)")

    # Find the existing chatgpt tab — do NOT open a new one.
    target = None
    for pg in ctx.pages:
        url = pg.url or ""
        print(f"  tab: {url[:90]}")
        if "chatgpt.com" in url or "chat.openai.com" in url:
            target = pg
    if target is None:
        print("FATAL: no existing chatgpt.com tab found — cannot inspect "
              "the timed-out generation. Leave the test tab open and retry.")
        browser.close()
        pw.stop()
        return 1

    print(f"\ninspecting tab: {target.url[:90]}")
    try:
        data = target.evaluate(_PROBE)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: evaluate failed: {exc}")
        browser.close()
        pw.stop()
        return 1

    print("\n--- role/turn probe ---")
    for k, v in data["altRole"].items():
        print(f"  {k}: {v}")

    rows = data["rows"]
    print(f"\n--- {len(rows)} <img> elements on page ---")
    for i, r in enumerate(rows):
        verdict = classify(r)
        print(f"\n[{i}] {verdict}")
        print(f"    src   : {r['src']}")
        print(f"    natural: {r['nW']}x{r['nH']}  attr: {r['w']}x{r['h']}")
        print(f"    alt   : {r['alt'][:70]!r}")
        print(f"    inAssistant={r['inAssistant']} inNav={r['inNav']} "
              f"inArticle={r['inArticle']} inTurn={r['inTurn']}")

    kept = [r for r in rows if classify(r) == "KEEP"]
    print(f"\n=== FIXED selector would KEEP {len(kept)} image(s) ===")
    for r in kept:
        print(f"  {r['nW']}x{r['nH']}  {r['src'][:100]}")
    # Do NOT close the user's tab.
    browser.close()
    pw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
