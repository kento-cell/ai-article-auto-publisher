"""Publish the AI sidejob 30-day roadmap article (2026-05-12, evidence-grounded).

A-grade evidence article (14/14 sources Tier 1-2, 21 citations, 5 visuals,
6 blockquote citations URL+date). Pre-generated images on disk, so we
skip ChatGPT image batch and call note_pub.publish_article directly.

Price: ¥1,980 (A+A grade tier in NotePublisher.determine_price).

After publish, the user adds this article to the AIプラン (membership
plan-limited 公開) manually from the creator dashboard, since plan
selection is not yet automated.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("publish_ai_sidejob_30day_roadmap")

DRAFT_PATH = _REPO / "data" / "articles" / "_drafts" / "ai_sidejob_30day_roadmap_20260512.md"
TITLE = (
    "【2026-05実証データ版】AI副業30日ロードマップ — "
    "月¥175,634クリエイターの公開実績から逆算した月¥5万達成の最短ルート"
)
SOURCE = (
    "AI sidejob roadmap (Claude-authored, evidence-grounded with 14 Tier1-2 sources)"
)

COVER = _REPO / "data" / "images" / "covers" / (
    "chatgpt_ai_sidejob_30day_roadmap_20260512_092315_892323_16560_cover.png"
)
INLINES = [
    _REPO / "data" / "images" / "covers" / (
        "chatgpt_ai_sidejob_30day_roadmap_20260512_092315_892323_16560_inline_00.png"
    ),
    _REPO / "data" / "images" / "covers" / (
        "chatgpt_ai_sidejob_30day_roadmap_20260512_092315_892323_16560_inline_01.png"
    ),
    _REPO / "data" / "images" / "covers" / (
        "chatgpt_ai_sidejob_retry_20260512_093719_490996_17184_inline_02_retry.png"
    ),
    _REPO / "data" / "images" / "covers" / (
        "chatgpt_ai_sidejob_retry_20260512_093719_490996_17184_inline_03_retry.png"
    ),
]


def _build_article_record(content: str) -> dict:
    return {
        "title": TITLE,
        "content": content,
        "platform": "note",
        "source": SOURCE,
        "scores": {
            "overall_grade": "A",
            "objective_grade": "A",
            "subjective_grade": "A",
            "evidence_level": "A",
            "numeric_score": 92.0,
            "metrics": {
                "citation_count": "A",
                "citation_format": "A",
                "visual_count": "A",
                "evidence_level": "A",
                "word_count": "B",
            },
        },
        "summary": (
            "未経験から30日でAI副業の初売上までを設計するロードマップ。"
            "クラシキログ氏(月¥175,634)・まい氏(月¥1万円)・いちのせSEO氏(月¥500万)の"
            "公開実績データ、各販売プラットフォーム公式手数料、"
            "CrowdWorks/Lancers/ココナラの2026年5月時点単価レンジを実証ベースで構成。"
            "Tier1-2ソース14個、blockquote引用6個、視覚要素5個。"
        ),
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    if not DRAFT_PATH.exists():
        logger.error("draft missing: %s", DRAFT_PATH)
        return 2
    if not COVER.exists():
        logger.error("cover missing: %s", COVER)
        return 5
    for p in INLINES:
        if not p.exists():
            logger.error("inline image missing: %s", p)
            return 5

    content = DRAFT_PATH.read_text(encoding="utf-8")
    logger.info(
        "draft loaded: %d chars, cover + %d inline images verified",
        len(content), len(INLINES),
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = _REPO / "data" / "articles" / f"note-AI-SIDEJOB-ROADMAP-{ts}.json"
    record = _build_article_record(content)
    out_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("record saved: %s", out_path.name)

    config_path = _REPO / "config" / "settings.yaml"
    config: dict = {}
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("settings.yaml unreadable (%s)", exc)

    from publishers.note_publisher import NotePublisher  # noqa: E402
    from generators.hashtag_generator import HashtagGenerator  # noqa: E402

    note_price = NotePublisher.determine_price("A", "A")  # ¥1,980
    logger.info(
        "starting note publish (price=¥%d, paid + planned membership, "
        "cover + %d inline pre-generated)",
        note_price, len(INLINES),
    )

    tags = HashtagGenerator(max_tags=10).generate(
        title=TITLE, content=content, source=SOURCE,
    )
    if not tags:
        tags = ["AI副業", "ChatGPT", "Claude", "副業", "AI活用", "マネタイズ"]
    logger.info("hashtags: %s", tags)

    url = None
    try:
        with NotePublisher() as note_pub:
            url = note_pub.publish_article(
                title=TITLE,
                content=content,
                tags=tags,
                price=note_price,
                cover_image_path=str(COVER),
                inline_image_paths=[str(p) for p in INLINES],
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("publish_article raised: %s", exc)
        return 3

    if not url:
        logger.error("publish returned None — see note publisher logs")
        return 4

    record["published_url"] = url
    record["published_at"] = datetime.now(timezone.utc).isoformat()
    out_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("PUBLISHED: %s", url)
    logger.info(
        "NOTE: メンバーシップ AIプラン限定公開 は手動追加してください "
        "(クリエイターページ → メンバーシップ → 記事 → 「メンバー特典記事を追加する」 "
        "→ ⋮ → メンバーシップに追加 → AIプラン)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
