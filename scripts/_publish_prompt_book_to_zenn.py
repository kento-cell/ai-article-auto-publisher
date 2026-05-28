"""Port scripts/_prompt_engineering_book.md to Zenn as a proper
*article* (not scrap). Zenn cap has been silently 404'ing pushes since
2026-04-17 (~41 days); user requested 2026-05-28 that we push a 技術書
to test whether high-quality long-form content gets past the cap where
short auto-generated articles don't.

Steps:
  1. Read scripts/_prompt_engineering_book.md (~54KB / 1357 lines)
  2. Strip the H1 title line (Zenn uses the frontmatter title instead)
  3. Build Zenn frontmatter (clean title — no 【】 brackets — + topics)
  4. Write to <ZENN_REPO>/articles/<slug>.md
  5. Use ZennPublisher to git add + commit + push
  6. Curl-probe to verify article actually rendered (not silently 404'd)

If 200: cap is content-quality-sensitive, future tech books can push through.
If 404: cap is volume/account-level, escalate (Zenn support / new account).
"""
from __future__ import annotations

import os
import re
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

import requests  # noqa: E402

from publishers.zenn_publisher import ZennPublisher  # noqa: E402

SOURCE = _REPO / "scripts" / "_prompt_engineering_book.md"

# Slug must be ≤ 50 chars, [a-z0-9-]+ only. Date prefix matches the
# convention in the existing zenn-content repo.
SLUG = "20260528-prompt-engineering-2026-3models"

# Clean title — 【】 clickbait brackets stripped because the cap MIGHT
# be triggered by aggressive titles (working hypothesis: cap fires on
# bracketed clickbait + thin content; this is bracket-free + heavy).
# Kept under ~80 chars to leave room for Zenn's auto-truncation.
TITLE = (
    "プロンプトエンジニアリング実務 2026 ― "
    "Claude 4.7 / GPT-5.5 / Gemini 3 のクセと案件で使う型"
)

# Zenn allows max 5 topics, lowercase a-z 0-9 hyphen. Stick to widely
# searched tags — these surface the article in tag feeds where readers
# actually browse.
TOPICS = ["ai", "llm", "claude", "chatgpt", "gemini"]

EMOJI = "🧠"


def _build_frontmatter() -> str:
    topics_yaml = "[" + ", ".join(f'"{t}"' for t in TOPICS) + "]"
    return (
        "---\n"
        f'title: "{TITLE}"\n'
        f'emoji: "{EMOJI}"\n'
        'type: "tech"\n'
        f"topics: {topics_yaml}\n"
        "published: true\n"
        "---\n\n"
    )


def _strip_h1(body: str) -> str:
    """Remove the first H1 line; Zenn derives title from frontmatter."""
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        # Eat the blank line right after if present, to avoid double-blank.
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines) + "\n"


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: source not found: {SOURCE}", file=sys.stderr)
        return 1

    body = SOURCE.read_text(encoding="utf-8")
    body = _strip_h1(body)

    repo_path = os.environ.get("ZENN_REPO_PATH")
    if not repo_path:
        print("ERROR: ZENN_REPO_PATH not set", file=sys.stderr)
        return 1
    articles_dir = Path(repo_path) / "articles"
    out_path = articles_dir / f"{SLUG}.md"

    if out_path.exists():
        print(f"ERROR: {out_path} already exists (would clobber)",
              file=sys.stderr)
        return 1

    out_path.write_text(_build_frontmatter() + body, encoding="utf-8")
    print(f"wrote: {out_path} ({out_path.stat().st_size} bytes)")

    pub = ZennPublisher(repo_path)
    print("publishing via git push…")
    ok = pub.publish(SLUG)
    if not ok:
        print("ERROR: git publish failed", file=sys.stderr)
        return 2

    # Give Zenn a few seconds to render after push, then curl.
    url = f"https://zenn.dev/zenn-user/articles/{SLUG}"
    print(f"verifying: {url}")
    for attempt in range(6):
        time.sleep(10)
        try:
            r = requests.head(url, timeout=20, allow_redirects=True)
            print(f"  attempt {attempt+1}: HTTP {r.status_code}")
            if r.status_code == 200:
                print("PASS — Zenn article is live; cap broken for "
                      "this push (high-quality 技術書 hypothesis)")
                return 0
            if r.status_code != 404:
                # 200 / 308 / 5xx — anything non-404 means it rendered or
                # is in some transient state. Treat 200 as success above;
                # log others and keep polling.
                continue
        except requests.RequestException as exc:
            print(f"  attempt {attempt+1}: probe error: {exc}")
    print(
        "FAIL — pushed but URL still 404 after 60s. "
        "Cap is NOT content-quality based — likely account/volume "
        "level. Escalation: contact Zenn support or rotate account."
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
