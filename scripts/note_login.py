"""One-time note.com login helper.

Launches a visible Chromium browser with a persistent user data directory
at ``data/note-profile``. The user logs in manually, then presses Enter
to save the session. Subsequent runs of ``NotePublisher`` reuse this
profile so automated publishing can run headless.

Usage:
    venv/Scripts/python.exe scripts/note_login.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Resolve profile dir relative to repository root so it works regardless
# of where the script is launched from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROFILE_DIR = _REPO_ROOT / "data" / "note-profile"


def main() -> int:
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"プロファイルディレクトリ: {_PROFILE_DIR}")

    import time
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(_PROFILE_DIR),
            channel="msedge",  # Use real Edge to bypass Google bot detection
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
            ],
        )
        # Remove webdriver flag
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://note.com/login")
        print("ブラウザが開きました。note.comにログインしてください。")
        print("ログイン完了を自動検出します（最大10分待機）...")

        # Poll for login success: URL no longer contains /login
        # and page has user menu or new-note link
        deadline = time.time() + 600  # 10 min
        logged_in = False
        while time.time() < deadline:
            time.sleep(3)
            try:
                current_url = page.url
                if "/login" not in current_url:
                    # Verify by checking for logged-in markers
                    page.goto("https://note.com/", timeout=10000)
                    time.sleep(2)
                    if "/login" not in page.url:
                        # Check for user menu or post button
                        content = page.content()
                        if any(m in content for m in [
                            "記事投稿", "投稿する", "/notes/new", "マイページ",
                        ]):
                            logged_in = True
                            break
            except Exception as e:
                print(f"待機中: {e}")

        if logged_in:
            print("✅ ログイン検出成功！プロファイルを保存します。")
            time.sleep(2)
        else:
            print("⚠️ タイムアウトしました。プロファイルは保存されますが、ログイン状態不明。")

        ctx.close()

    print(f"プロファイルを保存しました: {_PROFILE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
