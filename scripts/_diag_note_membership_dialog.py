"""Diagnostic v4 + first real add: drive the membership-add flow for ONE
article (116 = nb8a49e7d42e5) all the way to the dialog, dump the dialog
structure, then (best-effort, non-destructive) check the plan + confirm.

Flow confirmed by diag v1-v3 (2026-06-01):
  /notes → row[a href*=/n/<slug>] → button[aria-label='その他']
         → balloon button :has-text('メンバーシップ特典追加')
This script captures the LAST unknown: the dialog that opens after the
balloon item. It never clicks anything containing '解除'/'削除'/'キャンセル'.

Run headed:
    py scripts/_diag_note_membership_dialog.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_OUT = _REPO / "data" / "_diag"
SLUG = os.environ.get("DIAG_SLUG", "nb8a49e7d42e5")  # 116 緊急ケア


def _dump_dialog(page, tag: str) -> None:
    try:
        info = page.evaluate(
            """() => {
                const root = document.querySelector('[role=dialog],dialog,[aria-modal=true],.m-modal,[class*=modal]') || document.body;
                const txt = (root.innerText||'').slice(0,800);
                const btns = Array.from(root.querySelectorAll('button'))
                    .map(b => (b.innerText||'').trim() || (b.getAttribute('aria-label')||'')).filter(Boolean);
                const checks = Array.from(root.querySelectorAll("input[type=checkbox],[role=checkbox],[role=switch]"))
                    .map(c => ({checked: c.checked ?? c.getAttribute('aria-checked'),
                                lbl: (c.closest('label')?.innerText || c.getAttribute('aria-label') || '').trim().slice(0,40)}));
                return {txt, btns, checks,
                        hasDialog: !!document.querySelector('[role=dialog],dialog,[aria-modal=true]')};
            }"""
        )
        print(f"\n[{tag}] hasDialog={info.get('hasDialog')}")
        print(f"  innerText(trunc):\n   {info.get('txt','').replace(chr(10),' | ')[:500]}")
        print(f"  buttons: {info.get('btns')}")
        print(f"  checkboxes: {info.get('checks')}")
    except Exception as exc:
        print(f"  (dialog dump failed: {exc})")
    _OUT.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(_OUT / f"diag4_{tag}.png"), full_page=True)
        (_OUT / f"diag4_{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    from publishers.note_publisher import NotePublisher
    pub = NotePublisher(headless=False)
    pub._ensure_started()
    assert pub._page is not None
    page = pub._page
    try:
        pub._assert_logged_in()
        print("[login] OK")
        page.goto("https://note.com/notes", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        link = page.locator(f"a[href*='/n/{SLUG}']").first
        link.wait_for(state="visible", timeout=8000)
        card = link.locator("xpath=ancestor::*[.//button[@aria-label='その他']][1]")
        more = card.locator("button[aria-label='その他']").first
        more.scroll_into_view_if_needed()
        more.click(timeout=4000)
        page.wait_for_timeout(900)
        print(">>> opened その他 menu")

        item = page.locator("button:has-text('メンバーシップ特典追加')").first
        item.wait_for(state="visible", timeout=5000)
        item.click(timeout=3000)
        page.wait_for_timeout(1800)
        print(">>> clicked メンバーシップ特典追加・解除")
        _dump_dialog(page, "after_balloon_item")

        # Best-effort, non-destructive: check an UNCHECKED plan box, then
        # click a confirm button. Never touch 解除/削除/キャンセル.
        try:
            boxes = page.locator(
                "[role=dialog] input[type=checkbox], [role=dialog] [role=checkbox], "
                "[role=dialog] [role=switch], dialog input[type=checkbox]"
            )
            n = boxes.count()
            print(f">>> plan checkboxes found: {n}")
            for i in range(n):
                b = boxes.nth(i)
                try:
                    state = b.get_attribute("aria-checked")
                    is_checked = b.is_checked() if state is None else (state == "true")
                except Exception:
                    is_checked = False
                if not is_checked:
                    try:
                        b.check(timeout=2000)
                        print(f"   checked plan box #{i}")
                    except Exception:
                        b.click(timeout=2000)
                        print(f"   clicked plan box #{i}")
                    page.wait_for_timeout(400)
        except Exception as exc:
            print(f"  (checkbox handling skipped: {exc})")

        _dump_dialog(page, "after_check")

        confirm_texts = ["保存", "追加する", "設定する", "適用", "完了", "決定", "OK"]
        clicked = False
        for t in confirm_texts:
            try:
                btn = page.locator(
                    f"[role=dialog] button:has-text('{t}'), dialog button:has-text('{t}')"
                ).first
                if btn.count() > 0 and btn.is_visible(timeout=800):
                    label = (btn.inner_text() or "").strip()
                    if any(bad in label for bad in ("解除", "削除", "キャンセル")):
                        continue
                    btn.click(timeout=3000)
                    print(f">>> clicked confirm button: {label!r}")
                    clicked = True
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                continue
        if not clicked:
            print("!!! no confirm button matched — dialog may auto-apply or differ")
        _dump_dialog(page, "after_confirm")
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
