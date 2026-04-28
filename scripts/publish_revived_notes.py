"""Revive rejected note articles → publish via publish_custom_post.

For 2026-04-27 batch: pulls the 5 most-recent rejected note articles
whose only failure modes are ``citation_count`` and structural-template
``forbidden_phrases`` (now downgraded for note in
``objective_scorer.py``), generates ``data/custom_posts/*.json`` specs,
and shells out to ``publish_custom_post.py`` for each.

This is a one-off recovery script — not wired into the regular
pipeline. Sheets tracking is intentionally skipped because the rejected
sheet doesn't carry the ``article_id`` needed for the standard publish
flow; restoring full Sheets state would take more wiring than its
value here.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from dotenv import load_dotenv
load_dotenv()

from utils.sheets_manager import SheetsManager


# Title fragments to match against rejected sheet rows. Order = publish
# order. Each is paired with an image search query and a starter tag set
# (publish_custom_post.py blends with note's learned high-reach tags).
SELECTED = [
    {
        "match": "ChatGPT Projects",
        "image_query": "ai chatbot productivity assistant",
        "tags": ["AI", "ChatGPT", "Claude", "生成AI", "AI活用"],
    },
    {
        "match": "カウンター特化",
        "image_query": "japanese restaurant counter omakase sushi",
        "tags": ["グルメ", "東京グルメ", "デート", "ライフスタイル"],
    },
    {
        "match": "映像制作者",
        "image_query": "creative ai video editing studio",
        "tags": ["AI", "クリエイター", "映像制作", "AI活用", "生成AI"],
    },
    {
        "match": "2026年モデル比較",
        "image_query": "ai model comparison technology",
        "tags": ["AI", "ChatGPT", "Claude", "Gemini", "生成AI"],
    },
    {
        "match": "Zapier",
        "image_query": "automation workflow nocode productivity",
        "tags": ["AI", "ノーコード", "業務効率化", "自動化", "副業"],
    },
]


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9一-龯ぁ-ゔァ-ヴ_-]", "_", text)
    return text[:40]


def main() -> int:
    sm = SheetsManager()
    if sm._rejected_sheet is None:  # noqa: SLF001
        print("ERROR: rejected sheet not configured", file=sys.stderr)
        return 1

    all_rows = sm._rejected_sheet.get_all_records()  # noqa: SLF001
    note_rows = [
        r for r in all_rows
        if "note" in str(r.get("platform", "")).lower()
    ]
    print(f"Total rejected note rows: {len(note_rows)}")

    custom_dir = REPO / "data" / "custom_posts"
    custom_dir.mkdir(parents=True, exist_ok=True)

    # Build specs
    specs_to_run: list[Path] = []
    for sel in SELECTED:
        match_str = sel["match"]
        # Pick the LATEST row whose title contains the match string
        candidates = [
            r for r in note_rows
            if match_str in str(r.get("title", ""))
        ]
        if not candidates:
            print(f"  [skip] no match for {match_str!r}")
            continue
        # Sort by timestamp desc — last entry is the freshest attempt.
        candidates.sort(
            key=lambda r: str(r.get("timestamp", "")), reverse=True,
        )
        chosen = candidates[0]
        title = str(chosen.get("title", "")).strip()
        content = str(chosen.get("content", "")).strip()

        if not title or not content or len(content) < 500:
            print(f"  [skip] empty/short content for {match_str!r}")
            continue

        spec = {
            "platform": "note",
            "title": title,
            "image_query": sel["image_query"],
            "cover_image_query": sel["image_query"],
            "content": content,
            "tags": sel["tags"],
        }
        spec_path = custom_dir / f"revived_{_slugify(match_str)}.json"
        spec_path.write_text(
            json.dumps(spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        specs_to_run.append(spec_path)
        print(f"  [ready] {spec_path.name}  ({len(content)} chars)  {title[:60]}")

    if not specs_to_run:
        print("\nNo specs to publish. Aborting.")
        return 0

    print(f"\n=== Publishing {len(specs_to_run)} specs sequentially ===")
    py = REPO / "venv" / (
        "Scripts" if sys.platform == "win32" else "bin"
    ) / ("python.exe" if sys.platform == "win32" else "python")

    results: list[tuple[str, int]] = []
    for sp in specs_to_run:
        print(f"\n--- publishing: {sp.name} ---")
        rc = subprocess.call(
            [str(py), "scripts/publish_custom_post.py", str(sp)],
            cwd=str(REPO),
        )
        results.append((sp.name, rc))
        print(f"--- exit code: {rc} ---")

    print("\n=== Summary ===")
    for name, rc in results:
        status = "OK" if rc == 0 else f"FAIL(rc={rc})"
        print(f"  {status:10s}  {name}")
    return 0 if all(rc == 0 for _, rc in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
