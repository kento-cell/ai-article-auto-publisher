"""Retrofit KENTO cover images onto existing note.com posts.

Two-phase tool:

Phase A (local, safe) — ``python scripts/retrofit_note_covers.py --generate``:
    Reads ``data/articles/note-*.json``, extracts the Japanese display
    title from each article body, detects the genre, and renders a
    cover PNG into ``data/images/covers/``.

Phase B (remote, writes to note.com) — ``python scripts/retrofit_note_covers.py --upload``:
    Launches the persistent note.com session, navigates to the user's
    post list, matches each post to a generated cover by title, opens
    the editor, uploads the eyecatch, and saves. A ``--limit N`` flag
    caps how many posts are touched so you can proof-of-concept on one
    post first.

Phase B only runs when ``--upload`` is explicitly passed. Phase A is
the default.

Safety:
    * Phase B never calls ``edit_article`` and never touches the title
      or body — it only interacts with the eyecatch upload UI and the
      update button.
    * ``--limit 1`` lets you verify on a single post before touching the
      rest.
    * Screenshots of any failure are saved to ``logs/``.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from generators.affiliate_injector import AffiliateInjector  # noqa: E402
from generators.note_cover_generator import NoteCoverGenerator  # noqa: E402
from main import _extract_japanese_title  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("retrofit_note_covers")

_ARTICLES_DIR = _REPO_ROOT / "data" / "articles"
_COVERS_DIR = _REPO_ROOT / "data" / "images" / "covers"
_LOGS_DIR = _REPO_ROOT / "logs"


def _safe_slug(article_id: str) -> str:
    return article_id.replace(" ", "_").replace("/", "_")[:80]


def _load_note_articles() -> list[dict]:
    """Load all note-*.json files from the ArticleStore."""
    items: list[dict] = []
    for path in sorted(_ARTICLES_DIR.glob("note-*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("skip unreadable %s: %s", path.name, e)
            continue
        data["_path"] = str(path)
        items.append(data)
    return items


def phase_generate(articles: list[dict]) -> list[tuple[dict, Path]]:
    """Generate cover PNGs for each article. Returns (article, cover_path)."""
    injector = AffiliateInjector()
    # Reuse the genre detector — same logic used by the main pipeline.
    gen = NoteCoverGenerator(out_dir=_COVERS_DIR)

    results: list[tuple[dict, Path]] = []
    for a in articles:
        content = a.get("content") or ""
        jp_title = _extract_japanese_title(content) or a.get("title", "")
        if not jp_title:
            logger.warning("no title for %s — skipping", a.get("article_id"))
            continue
        # Detect genre from full text
        genre = injector._detect_genre(jp_title + " " + content)  # noqa: SLF001
        slug = _safe_slug(a.get("article_id", "cover"))
        out_path = _COVERS_DIR / f"{slug}.png"
        gen.generate(jp_title, genre=genre, out_path=out_path, slug=slug)
        logger.info(
            "generated cover: id=%s genre=%s title=%s",
            a.get("article_id"),
            genre,
            jp_title[:40],
        )
        a["_jp_title"] = jp_title
        a["_genre"] = genre
        results.append((a, out_path))
    return results


# ----------------------------------------------------------------------
# Phase B — Playwright upload
# ----------------------------------------------------------------------
def phase_upload(
    results: list[tuple[dict, Path]],
    limit: int | None,
    dry_run: bool,
) -> int:
    """Attach each generated cover to the corresponding note post.

    Opens the persistent note session, scrapes the post list, matches
    by title keyword, navigates to the editor, uploads the eyecatch,
    and saves. Returns the number of posts successfully updated.
    """
    from playwright.sync_api import (  # noqa: E402
        sync_playwright,
        TimeoutError as PWTimeout,
    )

    _LOGS_DIR.mkdir(exist_ok=True)
    profile_dir = _REPO_ROOT / "data" / "note-profile"
    if not profile_dir.exists():
        logger.error(
            "note profile dir missing: %s — run scripts/note_login.py first",
            profile_dir,
        )
        return 0

    updated = 0
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="msedge",
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Step 1: discover published posts (URL + title)
        posts = _discover_posts(page)
        if not posts:
            logger.error(
                "could not discover any posts; saved screenshot to logs/"
            )
            page.screenshot(path=str(_LOGS_DIR / "retrofit_discover_failed.png"), full_page=True)
            ctx.close()
            return 0

        logger.info("discovered %d post(s) on note", len(posts))
        for url, title in posts:
            logger.info("  %s — %s", url, title[:60])

        # Step 2: match generated covers to posts by title prefix
        pairs = _match_posts_to_covers(posts, results)
        logger.info("matched %d / %d cover(s) to posts", len(pairs), len(results))

        if limit is not None:
            pairs = pairs[:limit]
            logger.info("limited to %d post(s)", limit)

        # Step 3: for each pair, navigate and upload
        for url, cover_path, title in pairs:
            logger.info("processing: %s (%s)", title[:50], url)
            if dry_run:
                logger.info("  [DRY-RUN] would upload %s", cover_path)
                continue
            try:
                ok = _attach_cover(page, url, cover_path)
                if ok:
                    updated += 1
                    logger.info("  [OK] attached cover")
                else:
                    logger.error("  [FAIL] cover attach failed")
            except Exception as e:
                logger.exception("  [ERROR] %s", e)
                try:
                    ts = title[:20].replace(" ", "_")
                    page.screenshot(
                        path=str(_LOGS_DIR / f"retrofit_{_safe_slug(ts)}.png"),
                        full_page=True,
                    )
                except Exception:
                    pass

        ctx.close()

    return updated


def _discover_posts(page) -> list[tuple[str, str]]:
    """Discover the logged-in user's post list.

    Strategy:
      1. Go to https://note.com/ (dashboard when logged in).
      2. Extract the current user's username by inspecting header
         avatar/profile links.
      3. Navigate to ``https://note.com/{username}/all`` which lists
         every one of that user's posts.
      4. Scroll to trigger lazy loading, then scrape ``/n/...`` links.
    """
    # Step 1: open top page
    try:
        page.goto("https://note.com/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
    except Exception as e:
        logger.warning("top nav failed: %s", e)
        return []

    # Step 2: find the current user's profile path (e.g. "/kento_ai")
    username = page.evaluate(
        """() => {
            // Try several well-known locations for the current user's
            // profile link in the top navigation.
            const selectors = [
                'header a[href^="/"][aria-label*="マイページ"]',
                'header a[href^="/"][aria-label*="プロフィール"]',
                'a[href^="/"][data-testid*="user"]',
                'header nav a[href^="/"] img[alt]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const a = el.closest('a');
                    if (a && a.getAttribute('href')) return a.getAttribute('href');
                }
            }
            // Fallback: look for any header link that looks like /{username}
            // (single segment, no slashes, not /home, /search, etc).
            const deny = new Set(['home','search','login','signup','notifications','hashtag','mypage','dashboard','notes','info','settings','help','magazines','membership','creator','following','explore']);
            const links = Array.from(document.querySelectorAll('header a[href^="/"]'));
            for (const a of links) {
                const href = a.getAttribute('href') || '';
                const m = href.match(/^\\/([a-zA-Z0-9_]+)$/);
                if (m && !deny.has(m[1])) return href;
            }
            return null;
        }"""
    )

    # Prefer the creator dashboard which lists *all* your own posts
    # (published + draft + scheduled) with stable link patterns.
    dashboard_urls = [
        "https://note.com/notes",
        "https://note.com/notes/mine",
    ]
    loaded = False
    for u in dashboard_urls:
        try:
            page.goto(u, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            loaded = True
            break
        except Exception as e:
            logger.warning("nav fail %s: %s", u, e)
    if not loaded and username:
        # Fall back to public profile page
        try:
            page.goto(f"https://note.com{username}/all", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            loaded = True
        except Exception:
            pass
    if not loaded:
        return []

    # Trigger lazy loading
    for _ in range(8):
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(700)

    # Dashboard rows use router navigation without classic <a href>, so
    # sweep the full DOM HTML for any note ID pattern (n + 12+ hex chars).
    id_sweep = page.evaluate(
        """() => {
            const html = document.documentElement.outerHTML;
            const ids = new Set();
            const re = /n[a-f0-9]{12,}/g;
            let m;
            while ((m = re.exec(html)) !== null) ids.add(m[0]);
            return Array.from(ids);
        }"""
    )
    logger.info("dashboard id sweep: %d candidate(s)", len(id_sweep or []))

    # For each candidate ID, navigate to the editor, read the title, and
    # return the pair. This is slower than pure DOM scraping but robust
    # against the dashboard's SPA router and gives us authoritative titles.
    verified: list[tuple[str, str]] = []
    for sid in (id_sweep or []):
        edit_url = f"https://editor.note.com/notes/{sid}/edit/"
        try:
            page.goto(edit_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3500)
        except Exception as e:
            logger.warning("  skip %s (nav fail: %s)", sid, e)
            continue
        if "login" in page.url:
            logger.warning("  session expired while probing %s", sid)
            break
        # Read the current title from the editor's title textarea
        title = page.evaluate(
            """() => {
                const selectors = [
                    "textarea[placeholder*='タイトル']",
                    "input[placeholder*='タイトル']",
                    "[data-testid='editor-title']",
                    "h1",
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const v = el.value || el.textContent || '';
                        const t = v.trim();
                        if (t) return t;
                    }
                }
                return '';
            }"""
        )
        if not title:
            logger.info("  %s — (title empty, skipping)", sid)
            continue
        canon = f"https://note.com/_/n/{sid}"
        verified.append((canon, title))
        logger.info("  %s → %s", sid, title[:60])

    return verified

    # (Legacy anchor scraping kept below as additional fallback but we
    # now return from the verified-IDs path above.)
    posts = page.evaluate(
        """() => {
            const seen = {};
            const out = [];
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            // Real note IDs look like "n" + 12+ hex chars, e.g. n7b62e94e08c8
            const ID_RE = /(n[a-f0-9]{12,})/;
            for (const a of anchors) {
                const href = a.href || '';
                let id = null;
                // Match in any of the plausible URL patterns
                if (/\\/n\\//.test(href) || /\\/notes\\//.test(href) || /editor\\.note\\.com/.test(href)) {
                    const m = href.match(ID_RE);
                    if (m) id = m[1];
                }
                if (!id) continue;
                if (seen[id]) continue;

                // Walk up to a card-like ancestor and look for a title
                let text = '';
                let node = a;
                for (let depth = 0; depth < 5 && node; depth++) {
                    const h = node.querySelector && node.querySelector('h1, h2, h3, [class*="title" i], [class*="Title"]');
                    if (h && h.textContent) {
                        text = h.textContent;
                        break;
                    }
                    node = node.parentElement;
                }
                if (!text) text = a.textContent || '';
                text = text.trim().replace(/\\s+/g, ' ').slice(0, 200);
                if (!text) continue;
                // Always emit the canonical public URL so the edit
                // function can rewrite it to editor.note.com.
                const canon = 'https://note.com/_/n/' + id;
                seen[id] = 1;
                out.push([canon, text]);
            }
            return out;
        }"""
    )
    return posts or []


def _match_posts_to_covers(
    posts: list[tuple[str, str]],
    results: list[tuple[dict, Path]],
) -> list[tuple[str, Path, str]]:
    """Match note posts to generated covers by title keyword overlap."""
    pairs: list[tuple[str, Path, str]] = []
    used_urls: set[str] = set()
    for article, cover_path in results:
        jp_title = article.get("_jp_title", "")
        en_title = article.get("title", "")
        best_url = None
        best_score = 0
        best_title = ""
        for url, post_title in posts:
            if url in used_urls:
                continue
            score = _title_similarity(post_title, jp_title) + _title_similarity(post_title, en_title)
            if score > best_score:
                best_score = score
                best_url = url
                best_title = post_title
        if best_url and best_score >= 3:
            pairs.append((best_url, cover_path, best_title))
            used_urls.add(best_url)
        else:
            logger.warning(
                "no match for article %s (best_score=%d)",
                article.get("article_id"),
                best_score,
            )
    return pairs


def _title_similarity(a: str, b: str) -> int:
    """Very rough bag-of-characters similarity (longest common run)."""
    if not a or not b:
        return 0
    al = a.lower()
    bl = b.lower()
    # Count 4-char shingles present in both
    shingles_a = {al[i : i + 4] for i in range(len(al) - 3)}
    shingles_b = {bl[i : i + 4] for i in range(len(bl) - 3)}
    return len(shingles_a & shingles_b)


def _attach_cover(page, url: str, cover_path: Path) -> bool:
    """Navigate to the note editor for *url* and attach *cover_path*.

    The note editor places the eyecatch (見出し画像) at the very top of
    the content page, above the title textarea — NOT inside the publish
    settings panel. Flow:

        1. Go to editor.note.com/notes/{id}/edit/
        2. Find/click the "見出し画像を追加" button at the top of the page
        3. Upload via native file chooser or direct ``input[type=file]``
        4. Dismiss crop modal by clicking 保存
        5. Click 公開に進む → 更新する

    This never touches the title or body content.
    """
    import re as _re

    m = _re.search(r"/n/([a-zA-Z0-9]+)", url)
    if not m:
        logger.error("invalid url: %s", url)
        return False
    note_id = m.group(1)

    edit_url = f"https://editor.note.com/notes/{note_id}/edit/"
    page.goto(edit_url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(4000)

    # Scroll to top so the eyecatch row is in view
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)

    # Snapshot before any action for debugging
    try:
        page.screenshot(
            path=str(_LOGS_DIR / "retrofit_editor_top.png"),
            full_page=False,
        )
    except Exception:
        pass

    # Detect whether the eyecatch is already set. If so, skip upload and
    # go straight to the publish step (this happens on retry after a
    # previous run uploaded but failed to save publish state).
    already_has_cover = page.evaluate(
        """() => {
            // Heuristic: look for the 画像を追加 button. If it exists,
            // there is no cover yet. If missing, assume cover is set.
            const addBtn = document.querySelector('[aria-label="画像を追加"]');
            return !addBtn;
        }"""
    )
    if already_has_cover:
        logger.info("  eyecatch already present — skipping upload step")

    # The editor always has at least one hidden file input — setting
    # files on it bypasses the need to click a visible trigger.
    file_inputs = page.locator('input[type="file"]').all()
    logger.info("  editor has %d file input(s) at top-level", len(file_inputs))

    uploaded = bool(already_has_cover)
    if not uploaded and file_inputs:
        # Try each input until one accepts the file
        for i, fi in enumerate(file_inputs):
            try:
                fi.set_input_files(str(cover_path))
                uploaded = True
                logger.info("  uploaded via input #%d", i)
                break
            except Exception as e:
                logger.debug("  input #%d rejected: %s", i, e)
                continue

    if not uploaded:
        # Note's eyecatch area is a drop zone with no <input type=file>
        # — we synthesise a drop event carrying a File object made from
        # the PNG bytes (same technique as the in-body image uploader).
        import base64

        data = cover_path.read_bytes()
        b64 = base64.b64encode(data).decode()
        result = page.evaluate(
            """({b64, name}) => {
                const byteString = atob(b64);
                const ab = new ArrayBuffer(byteString.length);
                const ia = new Uint8Array(ab);
                for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
                const blob = new Blob([ab], {type: 'image/png'});
                const file = new File([blob], name, {type: 'image/png'});
                const dt = new DataTransfer();
                dt.items.add(file);

                // Find the eyecatch dropzone — the nearest ancestor
                // of the [aria-label="画像を追加"] button is the target.
                const btn = document.querySelector('[aria-label="画像を追加"]');
                if (!btn) return 'no-button';
                const zone = btn.closest('[data-dragging]') || btn.closest('div') || btn.parentElement;
                if (!zone) return 'no-zone';

                const rect = zone.getBoundingClientRect();
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;

                // Fire a full dragover → drop sequence. The dropzone
                // listens on the `drop` event and reads files from
                // dataTransfer.
                for (const type of ['dragenter', 'dragover', 'drop']) {
                    const ev = new DragEvent(type, {
                        bubbles: true,
                        cancelable: true,
                        clientX: cx,
                        clientY: cy,
                        dataTransfer: dt,
                    });
                    // DragEvent constructor ignores dataTransfer in some
                    // browsers, so force it via defineProperty
                    try {
                        Object.defineProperty(ev, 'dataTransfer', {value: dt});
                    } catch (_) {}
                    zone.dispatchEvent(ev);
                }
                return 'ok';
            }""",
            {"b64": b64, "name": cover_path.name},
        )
        logger.info("  drop event result: %s", result)
        if result == "ok":
            page.wait_for_timeout(4000)
            uploaded = True

    if not uploaded:
        logger.error("  could not upload cover image — dumping DOM snapshot")
        try:
            page.screenshot(
                path=str(_LOGS_DIR / "retrofit_no_eyecatch.png"),
                full_page=True,
            )
            html = page.content()
            (_LOGS_DIR / "retrofit_editor.html").write_text(html, encoding="utf-8")
        except Exception:
            pass
        return False

    # Wait for crop modal to render
    page.wait_for_timeout(4000)

    # Helper: check whether the crop modal is currently visible
    def _modal_visible() -> bool:
        try:
            loc = page.locator("[class*='CropModal']").first
            return loc.is_visible(timeout=400)
        except Exception:
            return False

    crop_selectors = [
        "[class*='CropModal'] button:has-text('保存')",
        "[class*='CropModal'] button:has-text('適用')",
        "[class*='CropModal'] button:has-text('完了')",
        "[class*='CropModal'] button:has-text('決定')",
        "[class*='CropModal'] button[type='submit']",
        "div[role='dialog'] button:has-text('保存')",
        "div[role='dialog'] button:has-text('適用')",
    ]

    # Click confirm and then wait for the modal to actually disappear.
    # Retry with different selectors if the click didn't close it.
    confirmed = False
    for attempt in range(3):
        if not _modal_visible():
            # No modal at all — maybe the upload auto-confirmed
            confirmed = True
            break
        clicked_this_round = False
        for sel in crop_selectors:
            try:
                b = page.locator(sel).first
                if b.is_visible(timeout=800):
                    b.click(timeout=3500, force=True)
                    clicked_this_round = True
                    logger.info("  crop click via %s (attempt %d)", sel, attempt + 1)
                    break
            except Exception:
                continue
        if not clicked_this_round:
            # Try blind 保存 anywhere on page as a last resort
            try:
                page.locator("button:has-text('保存')").first.click(timeout=2000, force=True)
                clicked_this_round = True
                logger.info("  crop click via global 保存 fallback")
            except Exception:
                pass
        # Wait up to 6 seconds for the modal to close
        for _ in range(12):
            page.wait_for_timeout(500)
            if not _modal_visible():
                confirmed = True
                break
        if confirmed:
            break

    try:
        page.screenshot(
            path=str(_LOGS_DIR / "retrofit_after_upload.png"),
            full_page=False,
        )
    except Exception:
        pass

    if not confirmed:
        logger.error("  crop modal did not close after retries; aborting")
        return False
    logger.info("  crop modal closed")

    # Click 公開に進む to get to publish settings
    proceed = [
        "button:has-text('公開に進む')",
        "button:has-text('公開設定')",
    ]
    proceeded = False
    for sel in proceed:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=3000)
                proceeded = True
                logger.info("  clicked: %s", sel)
                page.wait_for_timeout(3000)
                break
        except Exception:
            continue
    if not proceeded:
        logger.warning("  could not click 公開に進む")
        try:
            page.screenshot(path=str(_LOGS_DIR / "retrofit_no_proceed.png"), full_page=True)
        except Exception:
            pass
        return False

    # Personal-info modal interception: a 本人情報の登録 / 入力 dialog
    # sometimes pops up after 公開に進む for paid/monetised accounts and
    # blocks the update button from being hit-testable. Close it the
    # same way NotePublisher.edit_article does.
    for _text in ("本人情報の入力", "本人情報の登録"):
        try:
            if page.locator(f":text('{_text}')").first.is_visible(timeout=600):
                logger.info("  personal info modal detected — dismissing")
                for _sel in (
                    "button:has-text('キャンセル')",
                    "button[aria-label='閉じる']",
                    "button[aria-label='Close']",
                    "button:has-text('×')",
                    "[role='dialog'] button:first-child",
                ):
                    try:
                        _b = page.locator(_sel).first
                        if _b.is_visible(timeout=400):
                            _b.click(timeout=2000)
                            page.wait_for_timeout(600)
                            break
                    except Exception:
                        continue
                else:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(600)
                break
        except Exception:
            continue
    page.wait_for_timeout(1200)

    try:
        page.screenshot(path=str(_LOGS_DIR / "retrofit_publish_ready.png"), full_page=True)
    except Exception:
        pass

    # Click 更新する / 公開する — prefer 更新する since this is an edit
    update_selectors = [
        "button:has-text('更新する')",
        "button:has-text('公開する'):not(:has-text('予約'))",
        "button:has-text('投稿する'):not(:has-text('予約'))",
    ]
    for sel in update_selectors:
        try:
            btns = page.locator(sel).all()
            logger.info("  %s → %d match(es)", sel, len(btns))
            for b in reversed(btns):
                try:
                    if b.is_visible(timeout=500):
                        b.scroll_into_view_if_needed(timeout=2000)
                        b.click(timeout=3000)
                        page.wait_for_timeout(4000)
                        logger.info("  clicked update: %s", sel)
                        return True
                except Exception as e:
                    logger.debug("  click fail: %s", e)
                    continue
        except Exception:
            continue

    logger.error("  no update button found after 公開に進む")
    try:
        page.screenshot(path=str(_LOGS_DIR / "retrofit_no_update.png"), full_page=True)
    except Exception:
        pass
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true", help="Generate cover PNGs locally (default)")
    parser.add_argument("--upload", action="store_true", help="After generating, also upload to note.com")
    parser.add_argument("--limit", type=int, default=None, help="Limit how many posts to update (upload phase)")
    parser.add_argument("--dry-run", action="store_true", help="Upload phase: navigate but don't touch save buttons")
    args = parser.parse_args()

    if not args.generate and not args.upload:
        args.generate = True

    articles = _load_note_articles()
    logger.info("loaded %d note article(s)", len(articles))

    results = phase_generate(articles)
    logger.info("generated %d cover(s) in %s", len(results), _COVERS_DIR)

    if args.upload:
        count = phase_upload(results, limit=args.limit, dry_run=args.dry_run)
        logger.info("upload phase updated %d post(s)", count)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
