"""Fetch Amazon Associates tracking ID automatically.

Logs into Amazon Associates via Playwright (persistent profile) and
scrapes the tracking ID. Saves it to .env AMAZON_TRACKING_ID.

Usage:
    python scripts/amazon_tracking_id.py

On first run: manually log in to Amazon, then press Enter.
Subsequent runs: uses saved session.
"""

from __future__ import annotations

import io
import re
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

_ROOT = Path(__file__).resolve().parent.parent
_PROFILE = _ROOT / "data" / "amazon-profile"


def main() -> None:
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
        page.goto("https://affiliate.amazon.co.jp/home", timeout=60000)
        print("Amazonアソシエイトにログインしてください（初回のみ）")
        print("ログイン完了を自動検出します（最大5分）...")

        deadline = time.time() + 300
        tracking_id = None
        while time.time() < deadline:
            time.sleep(3)
            try:
                current = page.url
                # Check if we're on the home page
                if "affiliate.amazon.co.jp/home" in current or "associatecentral" in current:
                    # Try to find tracking ID in the page
                    content = page.content()
                    # Pattern: 数字-22 or 英字-22 (Amazon tracking ID format)
                    match = re.search(r"([a-zA-Z0-9_-]{3,20}-22)", content)
                    if match:
                        tracking_id = match.group(1)
                        break
                    # Try to navigate to account manager
                    try:
                        page.goto(
                            "https://affiliate.amazon.co.jp/home/account/manage_trackings",
                            timeout=15000,
                        )
                        time.sleep(2)
                        content = page.content()
                        match = re.search(r"([a-zA-Z0-9_-]{3,20}-22)", content)
                        if match:
                            tracking_id = match.group(1)
                            break
                    except Exception:
                        pass
            except Exception:
                pass

        if tracking_id:
            print(f"✅ トラッキングID検出: {tracking_id}")
            # Update .env
            env_path = _ROOT / ".env"
            if env_path.exists():
                env_content = env_path.read_text(encoding="utf-8")
                if "AMAZON_TRACKING_ID=" in env_content:
                    env_content = re.sub(
                        r"AMAZON_TRACKING_ID=.*",
                        f"AMAZON_TRACKING_ID={tracking_id}",
                        env_content,
                    )
                else:
                    env_content = env_content.rstrip() + f"\n\n# Amazon Associates\nAMAZON_TRACKING_ID={tracking_id}\n"
                env_path.write_text(env_content, encoding="utf-8")
                print(f"✅ .env更新完了")
            print(f"\n使える形式:")
            print(f"  商品URL + ?tag={tracking_id}")
            print(f"  https://www.amazon.co.jp/dp/XXXXXXXXXX?tag={tracking_id}")
        else:
            print("⚠️ トラッキングID検出失敗")
            print("手動で確認: https://affiliate.amazon.co.jp/home/account/manage_trackings")
            page.wait_for_timeout(30000)

        ctx.close()


if __name__ == "__main__":
    main()
