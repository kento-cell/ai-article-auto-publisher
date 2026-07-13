"""One-shot: open the 3D RAG vector graph HTML in Playwright and capture
multiple camera-angle screenshots for the #AIで遊ぼう contest entry.

Output:
  data/images/contest/rag_3d_overview.png  (default view, scrubbed of branding)
  data/images/contest/rag_3d_kbeauty.png   (zoomed at the K-beauty/past_articles cluster)
  data/images/contest/rag_3d_defenders.png (rotated to show hallucinations + ops_incidents islands)

Strategy: load the file:// URL → wait for plotly Scatter3d to mount →
camera-orbit via plotly relayout → screenshot the canvas region.
"""
from __future__ import annotations
import logging
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rag3d_shot")

SRC_HTML = Path.home() / "OneDrive" / "デスクトップ" / "rag_graph_3d.html"
OUT_DIR = _REPO / "data" / "images" / "contest"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Camera angles tuned to show distinct features of the 591-chunk space.
# plotly camera.eye is in scene units; default is around (1.25, 1.25, 1.25).
ANGLES = [
    {
        "name": "overview",
        "eye": {"x": 1.6, "y": 1.6, "z": 1.4},
        "center": {"x": 0, "y": 0, "z": 0},
        "caption": "全体俯瞰: 591 のベクトルが7つの色 (コレクション) に分かれて宇宙のように散らばっている",
    },
    {
        "name": "kbeauty_cluster",
        "eye": {"x": 0.6, "y": -1.8, "z": 1.2},
        "center": {"x": 0.2, "y": 0.1, "z": 0.05},
        "caption": "K-beauty クラスタ: 過去記事の青と成功パターンの緑が同じ意味空間で隣接",
    },
    {
        "name": "defenders_island",
        "eye": {"x": -1.4, "y": 1.6, "z": 0.6},
        "center": {"x": -0.1, "y": 0.0, "z": 0.0},
        "caption": "防御系コレクション (hallucinations / ops_incidents) は独立した島を作る",
    },
]


def main() -> int:
    from playwright.sync_api import sync_playwright
    if not SRC_HTML.exists():
        log.error("source HTML not found: %s", SRC_HTML)
        return 1

    src_url = SRC_HTML.as_uri()
    log.info("loading %s", src_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Large viewport for high-quality screenshot.
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()
        page.goto(src_url, wait_until="load", timeout=60_000)
        # plotly mounts asynchronously; wait until the main graph div exists
        # and at least one Scatter3d trace is drawn.
        try:
            page.wait_for_function(
                """() => {
                    const el = document.getElementById('net');
                    return el && el.querySelector('canvas');
                }""",
                timeout=30_000,
            )
        except Exception:
            # The 3D mode template uses a plotly div; fall back to any canvas.
            page.wait_for_selector("canvas", timeout=30_000)
        # Extra dwell so the legend and labels finish painting.
        time.sleep(4)

        # Find the plotly graph div id. The 3D template uses
        # `<div class="plotly-graph-div" id="<uuid>">` — discover it at runtime.
        graph_id = page.evaluate("""() => {
            const els = document.querySelectorAll('div.plotly-graph-div');
            return els.length ? els[0].id : null;
        }""")
        log.info("plotly graph id: %s", graph_id)

        for ang in ANGLES:
            if graph_id:
                # Re-aim the camera. Plotly.relayout takes the scene camera key.
                page.evaluate(
                    """({id, cam}) => {
                        return Plotly.relayout(id, {'scene.camera': cam});
                    }""",
                    {"id": graph_id, "cam": {"eye": ang["eye"], "center": ang["center"]}},
                )
                # let the WebGL frame settle
                time.sleep(2.5)
            out_path = OUT_DIR / f"rag_3d_{ang['name']}.png"
            page.screenshot(path=str(out_path), full_page=False)
            log.info("wrote %s  (%s)", out_path.name, ang["caption"])
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
