"""One-shot: regenerate the 28th note articles with the source-content
backfill fix and report content quality.

Controlled before/after test of the grounding fix (ops_incidents #18):
the same 4 Reddit-sourced topics that were fabricated from headlines are
re-run through the real generation path, which now backfills the linked
article body before building the prompt.
"""

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import main  # noqa: E402
from utils.token_manager import TokenManager  # noqa: E402

SOURCES = [
    {
        "title": (
            "Bill to block publishers from killing online games advances "
            "in California | Publishers would have to offer "
            "“independent” play patch or refunds after server "
            "shutdowns."
        ),
        "url": (
            "https://arstechnica.com/gaming/2026/05/bill-to-keep-online-"
            "games-playable-clears-key-hurdle-in-california/"
        ),
        "source": "reddit/r/technology",
        "content": "",
        "trend_score": 78.57,
    },
    {
        "title": "Xbox is rebranding to XBOX",
        "url": "https://www.theverge.com/news/931918/microsoft-xbox-rebrand-caps",
        "source": "reddit/r/technology",
        "content": "",
        "trend_score": 75.06,
    },
    {
        "title": "A History of IDEs at Google",
        "url": "https://laurent.le-brun.eu/blog/a-history-of-ides-at-google",
        "source": "reddit/r/programming",
        "content": "",
        "trend_score": 70.0,
    },
    {
        "title": (
            "Motorola Razr Fold review: Fits neatly in your pocket but "
            "not your budget ($1900)"
        ),
        "url": (
            "https://arstechnica.com/gadgets/2026/05/motorola-razr-fold-"
            "review-looking-for-an-edge"
        ),
        "source": "reddit/r/programming",
        "content": "",
        "trend_score": 70.0,
    },
]


def run() -> None:
    config = main.load_config()
    prompts = main.load_prompts()
    token_manager = TokenManager()
    claude, local_llm, use_local = main._init_llm(token_manager)
    if local_llm is None and claude is None:
        print("LLM unavailable — abort", flush=True)
        return
    template = prompts.get("note_article_prompt", "")

    for src in SOURCES:
        article = dict(src)
        print("\n" + "=" * 64, flush=True)
        print("GEN:", article["title"][:56], flush=True)
        print("=" * 64, flush=True)
        try:
            result = main._generate_single_article(
                article, "note", template,
                claude, local_llm, use_local,
                token_manager, config, prompts,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}", flush=True)
            continue
        if result is None:
            print("  -> None (generation failure)", flush=True)
        elif result.get("rejected"):
            print(f"  -> REJECTED: {result.get('reason')}", flush=True)
        else:
            scores = result.get("scores", {})
            print(
                f"  -> grade={scores.get('overall_grade')} "
                f"score={scores.get('numeric_score')} "
                f"slug={result.get('slug')} "
                f"content_chars={len(result.get('content', ''))}",
                flush=True,
            )

    if claude:
        claude.close()
    print("\nDONE", flush=True)


if __name__ == "__main__":
    run()
