"""Post the newest unpublished scrap .md drafts as Zenn scraps.

Identifies scraps in ``data/scraps/`` whose corresponding ArticleStore
entry has no ``published_url``, then publishes the top N (newest first)
as Zenn scraps via :class:`ZennScrapPublisher`. Writes ``published_url``
back to the store on success so subsequent runs skip them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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


def _extract_title(content: str, fallback: str) -> str:
    """Prefer the first plain-text body line as title. Scraps generated
    by the pipeline put the article title on line 1 as bare text (no
    Markdown ``#``) and put a ``## 参考文献`` section much later — so a
    naive first-heading scan picks up "参考文献" as title. Fall through
    to H1/H2 only when the document has no leading plain-text line."""
    plain_skip_prefixes = ("#", ">", "-", "*", "|", "```", "    ", "\t")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(plain_skip_prefixes):
            continue
        # Trim Zenn-incompatible leading bracket noise like 【】 left in
        # — keep the title concise. Cap at 100 chars.
        return stripped[:100]
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
        if stripped.startswith("## "):
            return stripped[3:].strip()
    return fallback


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=20,
                   help="max number of scraps to publish this run")
    p.add_argument("--max-age-hours", type=float, default=None,
                   help="skip drafts older than this many hours")
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be posted without posting")
    args = p.parse_args()

    scraps_dir = _REPO / "data" / "scraps"
    articles_dir = _REPO / "data" / "articles"

    # Build published-url map from store
    published: dict[str, str] = {}
    for jf in articles_dir.glob("*.json"):
        try:
            d = json.loads(jf.read_text(encoding="utf-8"))
            if d.get("published_url"):
                published[jf.stem] = d["published_url"]
        except Exception:
            pass

    def to_aid(stem: str) -> str:
        return stem.replace(" ", "_")

    # Collect unposted scraps
    candidates: list[tuple[str, Path]] = []
    for md in scraps_dir.glob("*.md"):
        stem = md.stem
        aid = to_aid(stem)
        if aid in published:
            continue
        candidates.append((stem, md))

    # Sort newest first
    candidates.sort(key=lambda x: x[1].stat().st_mtime, reverse=True)

    if args.max_age_hours is not None:
        cutoff = time.time() - args.max_age_hours * 3600
        candidates = [c for c in candidates if c[1].stat().st_mtime >= cutoff]

    selected = candidates[: args.limit]
    print(f"unposted total: {len(candidates)}; will process: {len(selected)}")

    if args.dry_run:
        for stem, md in selected:
            age_h = (time.time() - md.stat().st_mtime) / 3600
            print(f"  [dry] {age_h:6.1f}h  {stem}")
        return 0

    from publishers.zenn_scrap_publisher import ZennScrapPublisher

    # Reuse publish-time deny patterns from main.py for parity with the
    # primary publish loop — older drafts (pre-deny-list expansions) may
    # contain phrases that today's rules would block.
    import re as _re
    _DENY = [
        _re.compile(r"氏の\s*(?:Bluesky|Threads|Mastodon)\s*投稿"),
        _re.compile(r"(?:Bluesky|Threads|Mastodon)\s*投稿(?:が話題|を徹底|から徹底|から読み解)"),
        _re.compile(r"架空の\s*URL"),
        _re.compile(
            r"(?:〇〇|◯◯|○○|△△|××|□□|■■)"
            r"(?:寿司|寿し|鮨|焼鳥|やきとり|ラーメン|つけ麺|バル|バー|"
            r"ビストロ|食堂|酒場|割烹|蕎麦|そば|うどん|カレー|カフェ|"
            r"喫茶|ベーカリー|スイーツ|和菓子|洋菓子|焼肉|鉄板|串カツ|"
            r"串揚げ|天ぷら|うなぎ|もんじゃ|お好み焼|ピザ|フレンチ|"
            r"イタリアン|中華|韓国料理|タイ料理|居酒屋|ホルモン|"
            r"ジビエ|ステーキ|定食)"
        ),
        _re.compile(r"（\s*(?:仮名|仮称|架空|フィクション)\s*）"),
        _re.compile(
            r"本記事は[^\n]{0,20}"
            r"(?:AI|ChatGPT|Claude|Gemini|GPT|生成AI|人工知能)"
            r"[^\n]{0,40}(?:生成|作成|執筆|書き起こ|構成|編集)"
        ),
    ]

    def _deny_reason(s: str) -> str | None:
        for pat in _DENY:
            m = pat.search(s)
            if m:
                return m.group(0)[:60]
        return None

    posted = 0
    failed = 0
    skipped_deny = 0
    with ZennScrapPublisher(headless=True) as pub:
        for stem, md in selected:
            try:
                content = md.read_text(encoding="utf-8")
            except Exception as exc:
                print(f"  [read-err] {stem}: {exc}")
                failed += 1
                continue
            title = _extract_title(content, stem)
            reason = _deny_reason(title) or _deny_reason(content[:3000]) or _deny_reason(content[-3000:])
            if reason:
                print(f"skip (deny: {reason!r}): {title[:60]}")
                skipped_deny += 1
                continue
            print(f"posting: {title[:60]}")
            try:
                url = pub.publish_scrap(title=title, content=content)
            except Exception as exc:
                print(f"  FAILED: {exc}")
                failed += 1
                continue
            if not url:
                print("  FAILED: empty URL")
                failed += 1
                continue
            print(f"  OK: {url}")
            posted += 1
            # Persist URL back to store if possible
            aid = to_aid(stem)
            jf = articles_dir / f"{aid}.json"
            if jf.exists():
                try:
                    d = json.loads(jf.read_text(encoding="utf-8"))
                    d["published_url"] = url
                    jf.write_text(
                        json.dumps(d, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as exc:
                    print(f"  WARN: store write failed: {exc}")

    print()
    print(f"DONE — posted={posted}, failed={failed}, skipped_deny={skipped_deny}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
