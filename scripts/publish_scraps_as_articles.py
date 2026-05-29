"""Publish recent scrap draft files as full Zenn articles."""
from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from publishers.zenn_publisher import ZennPublisher


def extract_title(content: str) -> str:
    """Extract title from first H1/H2."""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
        if line.startswith("## "):
            return line[3:].strip()
    return "untitled"


def main() -> None:
    targets = [
        _ROOT / "data" / "scraps" / "zenn-Fast Spatial Memory .md",
        _ROOT / "data" / "scraps" / "zenn-HaloProbe_ Bayesian .md",
    ]

    zenn_repo = "E:/zenn-content"
    publisher = ZennPublisher(zenn_repo)

    for path in targets:
        if not path.exists():
            print(f"Not found: {path}")
            continue
        content = path.read_text(encoding="utf-8")
        title = extract_title(content)
        print(f"Publishing: {title[:60]}")
        try:
            slug = publisher.create_article(
                title=title,
                content=content,
                topics=["ai", "tech", "machinelearning"],
                article_type="tech",
            )
            success = publisher.publish(slug)
            print(f"  slug: {slug}")
            print(f"  published: {success}")
            if success:
                print(f"  https://zenn.dev/{os.environ.get('ZENN_USERNAME', '')}/articles/{slug}")
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
