"""Regenerate published note articles that were fabricated from headlines
(ops_incidents #18).

Each listed article is re-run through the real generation path, which
now backfills the linked article body before building the prompt. The
regenerated content overwrites `data/articles/{slug}.json` while the
original `published_url` / `article_id` are preserved so a later
edit_article pass can replace the live note.com body.

Newest-first order — paid articles (published on/after 2026-05-12,
per the all-paid pricing policy) come first.

Usage:
    py scripts/_regen_published_garbage.py            # all
    py scripts/_regen_published_garbage.py --limit 5  # first 5 only
    py scripts/_regen_published_garbage.py --start 5  # skip first 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# Load .env before importing main so LLM_MODEL_* / HF_HUB_OFFLINE apply.
_ENV = _REPO / ".env"
if _ENV.exists():
    import os
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import main  # noqa: E402
from utils.token_manager import TokenManager  # noqa: E402

# Fabricated published note articles, newest-first (see _audit_published_garbage.py).
SLUGS = [
    "note-Power_Prices_in_East-0f01ad1a",
    "note-The_Feed_Is_Fake___T-07050ae5",
    "note-70__of_Americans_opp-294e48e2",
    "note-Cisco_announces_reco-35d8aaaf",
    "note-Microsoft_BitLocker--0453c2b8",
    "note-Microsoft_confirms_W-abf3b1df",
    "note-Nearly_50_000_Lake_T-3264c8b9",
    "note-OpenAI_now_wants_Cha-209675b8",
    "note-The_AI_Layoff_Bill_I-1ed0597d",
    "note-Zero-day_exploit_com-ce4a843a",
    "note-_Everyone_is_unhappy-f89b5415",
    "note-5_Years_and__5M_Late-f1b21453",
    "note-Cisco_s_stock_pops_1-5224bf4f",
    "note-Louis_Rossmann_taunt-c4a7127a",
    "note-Microsoft_s_Edge_Cop-d04dd4f6",
    "note-PCOS_Is_Officially_R-34291c12",
    "note-Louis_Rossmann_tells-d59475f2",
    "note-Reddit_Starts_Blocki-9e0633a0",
    "note-_Cannot_be_explained-5f05d53b",
    "note-Judge_rules_DOGE_use-b4394f01",
    "note-Cloudflare_lays_off_-68fac977",
    "note-GameStop_CEO_says_eB-0a33f278",
]

_ARTICLES = _REPO / "data" / "articles"


def _field(source_str: str, key: str) -> str:
    m = re.search(rf"'{key}': '([^']*)'", source_str)
    return m.group(1) if m else ""


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument(
        "slugs", nargs="*",
        help="explicit slugs to regenerate (overrides the built-in list)",
    )
    args = parser.parse_args()

    targets = args.slugs if args.slugs else SLUGS[args.start:]
    if args.limit > 0:
        targets = targets[: args.limit]

    config = main.load_config()
    prompts = main.load_prompts()
    token_manager = TokenManager()
    claude, local_llm, use_local = main._init_llm(token_manager)
    template = prompts.get("note_article_prompt", "")

    ok = 0
    for slug in targets:
        path = _ARTICLES / f"{slug}.json"
        if not path.exists():
            print(f"SKIP (missing): {slug}", flush=True)
            continue
        original = json.loads(path.read_text(encoding="utf-8"))
        source_str = original.get("source", "")
        if not isinstance(source_str, str):
            source_str = json.dumps(source_str)
        article = {
            "title": original.get("title", ""),
            "url": _field(source_str, "url"),
            "source": _field(source_str, "source") or "reddit/r/technology",
            "content": "",
            "trend_score": 70.0,
        }
        print("\n" + "=" * 64, flush=True)
        print("REGEN:", article["title"][:56], flush=True)
        print("=" * 64, flush=True)
        if not article["url"]:
            print("  SKIP — no source url", flush=True)
            continue
        try:
            result = main._generate_single_article(
                article, "note", template,
                claude, local_llm, use_local,
                token_manager, config, prompts,
                _skip_save=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}", flush=True)
            continue
        if result is None or result.get("rejected"):
            reason = result.get("reason") or result.get(
                "rejection_reasons", "?"
            ) if result else "None"
            print(f"  -> NOT SAVED ({reason})", flush=True)
            continue

        # Preserve the live mapping; overwrite only the regenerated fields.
        merged = dict(original)
        merged["content"] = result["content"]
        merged["scores"] = result["scores"]
        merged["source"] = str(result["source"])
        if result.get("cover_image"):
            merged["cover_image"] = str(result["cover_image"])
        path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        scores = result.get("scores", {})
        print(
            f"  -> SAVED grade={scores.get('overall_grade')} "
            f"score={scores.get('numeric_score')} "
            f"chars={len(result['content'])}",
            flush=True,
        )
        ok += 1

    if claude:
        claude.close()
    print(f"\nDONE — {ok}/{len(targets)} regenerated", flush=True)


if __name__ == "__main__":
    run()
