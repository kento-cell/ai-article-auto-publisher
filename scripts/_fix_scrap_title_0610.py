# -*- coding: utf-8 -*-
"""One-shot (2026-06-10): fix fabricated scrap title on Zenn.

The publish-time 日本語タイトル抽出 step promoted a body H1
「【100人に聞いた】...」 to the scrap title, but the body contains no
survey — a title-fabrication violation. Remove the fabricated prefix.

Usage:
    py scripts/_fix_scrap_title_0610.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publishers.zenn_scrap_publisher import ZennScrapPublisher  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCRAP_URL = "https://zenn.dev/kento_cell/scraps/fb51639f490b4a"
NEW_TITLE = (
    "マルチテナントDB移行で失敗しないための"
    "「PostgreSQLアーキテクチャ設計」完全ガイド"
)


def main() -> int:
    pub = ZennScrapPublisher(headless=True)
    try:
        pub._ensure_started()
        page = pub._page
        assert page is not None
        page.goto(SCRAP_URL, timeout=30000)
        page.wait_for_timeout(3000)

        if "enter" in page.url or "login" in page.url:
            logger.error("Zenn login expired — run scripts/zenn_login.py")
            return 1

        # Owner view: title row has an edit button. Try known affordances.
        candidates = [
            "button[aria-label='タイトルを編集']",
            "button:has-text('タイトルを編集')",
            "h1 ~ button",
            "header button:has(svg)",
        ]
        clicked = False
        for sel in candidates:
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=3000)
                loc.click()
                clicked = True
                logger.info("edit affordance clicked: %s", sel)
                break
            except Exception:
                continue

        if not clicked:
            # Dump nearby controls for diagnosis
            logger.error("no edit affordance found — dumping header buttons")
            for el in page.locator("button").all()[:30]:
                try:
                    label = el.get_attribute("aria-label") or el.inner_text()
                    logger.info("  button: %r", label[:60])
                except Exception:
                    pass
            page.screenshot(path="logs/_scrap_title_fix_fail.png", full_page=False)
            return 2

        # Title edit field appears (textarea or input pre-filled with title)
        page.wait_for_timeout(1000)
        field = None
        for sel in ("textarea", "input[type='text']"):
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=4000)
                val = loc.input_value()
                if "100人に聞いた" in val or "マルチテナント" in val:
                    field = loc
                    break
            except Exception:
                continue
        if field is None:
            logger.error("title edit field not found")
            page.screenshot(path="logs/_scrap_title_fix_fail.png")
            return 3

        field.fill(NEW_TITLE)
        page.wait_for_timeout(500)

        # Confirm: 更新する / 保存 button
        for sel in (
            "button:has-text('更新する')",
            "button:has-text('保存')",
            "button[type='submit']",
        ):
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=3000)
                loc.click()
                logger.info("save clicked: %s", sel)
                break
            except Exception:
                continue

        page.wait_for_timeout(3000)
        page.reload()
        page.wait_for_timeout(2000)
        h1 = page.locator("h1").first.inner_text()
        logger.info("post-fix h1: %s", h1[:80])
        if "100人に聞いた" in h1:
            logger.error("title still contains fabricated claim")
            page.screenshot(path="logs/_scrap_title_fix_fail.png")
            return 4
        logger.info("OK — fabricated prefix removed")
        return 0
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
