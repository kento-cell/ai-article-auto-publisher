"""One-shot: 2026-07-28 review remediation (user-approved).

1. Repost bodies to the 2 EMPTY zenn scraps (incident #27) after
   cleaning prompt-leaks / broken image markdown / placeholders.
2. Fix 色覚 note article: legal-standard misinformation + trailing
   empty diagram heading.
3. Fix 韓国ガジェット note article: unsourced BTS claim + meta leak
   (sanitizer's new rules handle the meta line automatically).

Usage: py scripts/_fix_review_20260728.py <zenn|note>
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fix_0728")

_REPO = Path(__file__).resolve().parent.parent
_NOTE_USER = os.environ.get("NOTE_USER", "")


def _clean_for_zenn(content: str) -> str:
    from generators.content_sanitizer import sanitize
    from utils.url_cleaner import clean_article_urls

    c, removed = sanitize(content)
    logger.info("sanitize removed %d artifact(s)", len(removed))
    c = clean_article_urls(c)
    # Broken local-image markdown `![...](data/images/... ")` — zenn
    # cannot resolve local paths at all; drop the whole line.
    c, n = re.subn(r"^!\[[^\]]*\]\([^)\n]*data/images[^)\n]*\)?[^\n]*$\n?",
                   "", c, flags=re.MULTILINE)
    logger.info("local-image lines dropped: %d", n)
    # Unresolved placeholder 「月間$Xの機会損失」
    c = c.replace("月間$Xの機会損失", "月単位の機会損失")
    # Meta self-summary footer 「***[筆者の見解]*** 本記事は…」
    c = re.sub(r"^\*{0,3}\[筆者の見解\]\*{0,3}[^\n]*本記事[^\n]*$\n?", "",
               c, flags=re.MULTILINE)
    # Mermaid label parens `A[X (Y)]` -> `A[X - Y]` (syntax error fix)
    def _fix_label(m: re.Match[str]) -> str:
        inner = m.group(2).replace("(", "- ").replace(")", "").strip()
        return f"{m.group(1)}[{inner}]"
    c = re.sub(r"(\b[A-Z]\d?)\[([^\]\n]*\([^\]\n]*\)[^\]\n]*)\]", _fix_label, c)
    return c


def do_zenn() -> int:
    from publishers.zenn_scrap_publisher import ZennScrapPublisher

    targets = []
    import glob
    for f in glob.glob(str(_REPO / "data" / "articles" / "*.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        u = str(d.get("published_url", ""))
        for sid in ("c6a09ce3e783d4", "4458d6a3bf1d38"):
            if sid in u:
                targets.append((sid, u, d))
    if len(targets) != 2:
        logger.error("expected 2 targets, found %d", len(targets))
        return 1

    failures = 0
    with ZennScrapPublisher(headless=True) as pub:
        for sid, url, d in targets:
            content = d.get("content", "")
            lines = content.split("\n", 1)
            body = lines[1].lstrip("\n") if len(lines) > 1 else content
            body = _clean_for_zenn(body)
            logger.info("[%s] reposting %d chars", sid, len(body))
            ok = pub.add_post_to_scrap(url.split("?")[0], body)
            logger.info("[%s] repost + verify: %s", sid, ok)
            if not ok:
                failures += 1
    return failures


def do_note() -> int:
    from publishers.note_publisher import NotePublisher
    from generators.content_sanitizer import sanitize, trim_incomplete_tail
    import glob

    def load(frag):
        for f in glob.glob(str(_REPO / "data" / "articles" / "*.json")):
            p = Path(f)
            d = json.loads(p.read_text(encoding="utf-8"))
            if frag in str(d.get("published_url", "")):
                return p, d
        raise SystemExit(f"not found: {frag}")

    jobs = []

    # 色覚 (n6735c0f8edc4)
    p, d = load("n6735c0f8edc4")
    c = d["content"]
    old = "色のコントラスト比は法律的な基準が存在します"
    if old in c:
        c = c.replace(
            old,
            "色のコントラスト比には WCAG という国際的なアクセシビリティ"
            "ガイドラインの推奨基準があります（法律上の義務ではありません）",
        )
    # trailing empty diagram heading (「✨ 知識の構造化フロー図…」)
    ed, sep, foot = c.partition("<!-- AFFILIATE_SECTION -->")
    ed = re.sub(r"^#{1,4}[^\n]*知識の構造化フロー図[^\n]*$\n?", "", ed,
                flags=re.MULTILINE)
    ed, _ = trim_incomplete_tail(ed)
    c = ed + ("\n\n" + sep + foot if sep else "")
    jobs.append(("shikikaku", p, d, "n6735c0f8edc4", c))

    # 韓国ガジェット (n19627ac61c2f)
    p, d = load("n19627ac61c2f")
    c = d["content"]
    # BTS 無ソース断定文 (文単位で削除)
    c, n = re.subn(r"[^\n。]*Jungkook[^\n。]*。", "", c)
    logger.info("BTS sentences removed: %d", n)
    # メタ漏れ行は sanitizer 新規則が除去
    ed, sep, foot = c.partition("<!-- AFFILIATE_SECTION -->")
    ed, removed = sanitize(ed)
    logger.info("sanitize removed: %s", [r[:40] for r in removed])
    c = ed + ("\n\n" + sep + foot if sep else "")
    jobs.append(("gadget", p, d, "n19627ac61c2f", c))

    pub = NotePublisher()
    failures = 0
    try:
        for key, path, d, note_key, new_content in jobs:
            lines = new_content.split("\n", 1)
            body = lines[1].lstrip("\n") if len(lines) > 1 else new_content
            ok = pub.edit_article(
                url=f"https://note.com/{_NOTE_USER}/n/{note_key}",
                new_content=body,
            )
            logger.info("[%s] edit_article: %s", key, ok)
            if not ok:
                failures += 1
                continue
            d["content"] = new_content
            d["fixed_at"] = "2026-07-28"
            d["fix_reason"] = "review: misinformation/BTS/meta-leak fixes"
            path.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    finally:
        pub.close()
    return failures


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "zenn":
        raise SystemExit(do_zenn())
    if mode == "note":
        raise SystemExit(do_note())
    print("Usage: py scripts/_fix_review_20260728.py <zenn|note>")
    raise SystemExit(1)
