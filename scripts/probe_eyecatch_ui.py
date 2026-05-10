"""Probe note.com editor eyecatch UI for replace strategy.

Opens the K-beauty article in editor.note.com and dumps:
  - screenshot of the eyecatch area before/after click
  - all aria-labels near the eyecatch image
  - all buttons in the top region of the page

Goal: find the right selectors/interactions to delete or replace the
existing eyecatch when force_replace=True.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

LOGS = _REPO / "data" / "_eyecatch_probe"
LOGS.mkdir(parents=True, exist_ok=True)


def main() -> int:
    from publishers.note_publisher import NotePublisher

    target_url = "https://editor.note.com/notes/nd0cb235da4a6/edit/"

    pub = NotePublisher(headless=False)
    try:
        pub._ensure_started()
        page = pub._page
        assert page is not None
        page.goto(target_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        page.screenshot(path=str(LOGS / "before.png"), full_page=False)

        # Dump the eyecatch image rect and all surrounding aria-labels.
        info = page.evaluate(
            """() => {
                const out = {};
                const img = document.querySelector('img[alt="eyecatch"]');
                if (!img) {
                    out.eyecatch_img = null;
                } else {
                    const r = img.getBoundingClientRect();
                    out.eyecatch_img = {
                        src: img.src,
                        rect: {x: r.left, y: r.top, w: r.width, h: r.height},
                    };
                }
                // All elements with aria-label in the top 800px of the page.
                const labelled = Array.from(document.querySelectorAll('[aria-label]'))
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.top < 800;
                    })
                    .map(el => ({
                        tag: el.tagName.toLowerCase(),
                        label: el.getAttribute('aria-label'),
                        rect: (() => {
                            const r = el.getBoundingClientRect();
                            return {x: r.left, y: r.top, w: r.width, h: r.height};
                        })(),
                        visible: el.offsetParent !== null,
                    }));
                out.aria_top = labelled;
                // Count file inputs.
                out.file_inputs = document.querySelectorAll('input[type="file"]').length;
                return out;
            }"""
        )
        (LOGS / "before.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("--- BEFORE ---")
        print(json.dumps(info, ensure_ascii=False, indent=2)[:3000])

        # Click the eyecatch — does a toolbar with delete/replace appear?
        if info.get("eyecatch_img"):
            r = info["eyecatch_img"]["rect"]
            cx = r["x"] + r["w"] / 2
            cy = r["y"] + 40
            page.mouse.move(cx, cy)
            page.wait_for_timeout(400)
            page.mouse.click(cx, cy)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(LOGS / "after_click.png"), full_page=False)

            after = page.evaluate(
                """() => Array.from(document.querySelectorAll('[aria-label],button'))
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.top < 800 && r.width > 0 && r.height > 0;
                    })
                    .map(el => ({
                        tag: el.tagName.toLowerCase(),
                        label: el.getAttribute('aria-label'),
                        text: (el.textContent || '').trim().slice(0, 40),
                        rect: (() => {
                            const r = el.getBoundingClientRect();
                            return {x: r.left, y: r.top, w: r.width, h: r.height};
                        })(),
                    }))"""
            )
            (LOGS / "after_click.json").write_text(
                json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("--- AFTER CLICK ---")
            print(json.dumps(after, ensure_ascii=False, indent=2)[:3000])

        page.wait_for_timeout(2000)
    finally:
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
