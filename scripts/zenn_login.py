"""One-time Zenn login helper for scrap auto-posting.

Launches Edge with a persistent profile at data/zenn-profile/.
Log in manually via GitHub OAuth, then close the browser.
Subsequent zenn scrap posting uses this session.
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

_ROOT = Path(__file__).resolve().parent.parent
_PROFILE = _ROOT / "data" / "zenn-profile"


def main() -> int:
    _PROFILE.mkdir(parents=True, exist_ok=True)
    print(f"プロファイル: {_PROFILE}")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(_PROFILE),
            channel="msedge",
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
            ],
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://zenn.dev/enter")
        print("Zennにログインしてください（GitHub/Google等）。")
        print("ログイン完了を自動検出します（最大10分待機）...")

        deadline = time.time() + 600
        logged_in = False
        while time.time() < deadline:
            time.sleep(3)
            try:
                current_url = page.url
                if "/enter" not in current_url:
                    page.goto("https://zenn.dev/dashboard", timeout=10000)
                    time.sleep(2)
                    if "/enter" not in page.url and "/login" not in page.url:
                        logged_in = True
                        break
            except Exception:
                pass

        if logged_in:
            print("✅ ログイン検出成功。")
            time.sleep(2)
        else:
            print("⚠️ タイムアウト。")

        ctx.close()

    print(f"プロファイル保存: {_PROFILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
