"""One-time interactive login for ChatGPT in the Brave profile.

Run this once. A non-headless Brave window opens at chatgpt.com.
Log in (email/password or Google SSO). When you see your normal
ChatGPT chat list, close the window. Login state persists in
``data/chatgpt-profile/`` for subsequent automated runs.

Usage::

    py scripts/chatgpt_login.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from playwright.sync_api import sync_playwright

PROFILE_DIR = REPO / "data" / "chatgpt-profile"
BRAVE_PATH = (
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
)


def main() -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("Opening Brave with persistent profile…")
    print(f"Profile dir: {PROFILE_DIR}")
    print()
    print("Please log in to ChatGPT. When done, close the browser window.")
    print("(The profile is saved automatically on close.)")
    print()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=BRAVE_PATH,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://chatgpt.com/")
        # Block until the user closes the window.
        try:
            ctx.wait_for_event("close", timeout=0)
        except Exception:  # noqa: BLE001
            pass
    print("Login session saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
