"""Regenerate note article eyecatches in a 'Smash Bros 参戦!!' homage style.

The user's request (2026-05-01): for the just-published articles,
swap the bland Unsplash covers for ChatGPT-generated images that
visualize the article subject inside a fight-game-announcement
aesthetic — black ink-splash burst, vivid cyan motion-blur backdrop,
bold gold-with-red-outline 「参戦!!」 text. Trademark caution: do NOT
mention Nintendo / 大乱闘スマッシュブラザーズ in the prompt; only
describe the visual idiom (ink splash, cyan, gold 参戦!! text). The
generator declines if a registered franchise is named.

Per-article subject hint comes from `--subjects` JSON or, by default,
from a built-in mapping that captures the iconic visual for each
article we just published. A Gemma3-via-LocalLLM step would be more
general but adds latency; for the current 3-article batch the
hand-tuned hints are clearer than what the LLM picked.

Usage::

    python scripts/regen_eyecatch_smash_style.py            # dry run
    python scripts/regen_eyecatch_smash_style.py --apply    # generate + swap
    python scripts/regen_eyecatch_smash_style.py --apply --only "1X Neo"
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
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
logger = logging.getLogger("regen_smash")


_STYLE_BLOCK: str = (
    "格闘ゲームの新キャラクター参戦発表風のキービジュアル。"
    "シアン (鮮やかな青〜白の光) のスピード感あるグラデーション背景に、"
    "画面手前へ飛び散る黒い墨スプラッシュが大胆に配置されている。"
    "中央には記事の象徴となる被写体のシルエットが堂々と立ち、"
    "左下には極太のゴールド黄色＋赤い縁取りで日本語の「参戦!!」テキストを大きく入れる。"
    "レトロアニメの予告編のような迫力と勢いを最優先。"
    "光のラインや風の跡で前進感を強調。色味は黒・シアン・ゴールド黄・白の4色基調。"
    "16:9 横長 (1792×1024 ピクセル)。テキストは「参戦!!」のみ、それ以外の文字は描かない。"
)


def _build_prompt(article_title: str, subject_hint: str) -> str:
    return (
        "以下の記事のサムネイル画像を、指定スタイルで作成してください。\n\n"
        "【記事タイトル】\n"
        f"{article_title}\n\n"
        "【中央に描く被写体】\n"
        f"{subject_hint}\n\n"
        "【スタイル】\n"
        f"{_STYLE_BLOCK}\n\n"
        "出力は画像のみ。"
    )


# Hand-tuned subject hints for the 3 articles published 2026-05-01.
# Adding new entries is fine; partial-string match wins.
_DEFAULT_SUBJECTS: dict[str, str] = {
    "4ツールの得意領域": (
        "4種類のAIコーディング支援ツールを象徴する4つの抽象アイコン (キーボード、"
        "スピードライン、コードブロック、稲妻) が縦に並んで配置されたシルエット"
    ),
    "3フレームワーク": (
        "ローカルLLMサーバー (PCタワーとGPU) を中心に、3つのフレームワークの"
        "抽象アイコンが衛星のように並んでいるシルエット"
    ),
    "1X Neo": (
        "家庭の居間で立ち上がる人型ヒューマノイドロボットのシルエット。背景に"
        "工場のロボットと家庭のロボットを対比させた構図。1X Neo を象徴する"
        "細身でしなやかな姿勢"
    ),
    "VLA時代": (
        "AIエンジニアがロボティクスの世界へ踏み出す瞬間を象徴する、"
        "学習者の人物シルエットと、その背後にそびえる産業ヒューマノイドロボットが"
        "重なる二重シルエット構図"
    ),
    # Catch-all fallback if --only matches none of the above.
    "_default": (
        "記事タイトルから連想される最も象徴的な物体や人物のシルエット"
    ),
}


def _pick_subject(title: str, overrides: dict[str, str]) -> str:
    for key, hint in {**overrides, **_DEFAULT_SUBJECTS}.items():
        if key == "_default":
            continue
        if key in title:
            return hint
    return _DEFAULT_SUBJECTS["_default"]


def kill_brave() -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "brave.exe"],
            check=False, capture_output=True,
        )
        logger.info("brave.exe killed (or wasn't running)")
        time.sleep(2)
    except Exception as exc:
        logger.warning("kill_brave failed: %s", exc)


def collect_targets(only: str | None):
    """Pick the most-recently-published note articles. We target the
    just-shipped batch by default — articles whose JSON has a
    published_url and whose published_at is on today's date — so a
    naive --apply doesn't accidentally rewrite covers on older posts.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    out: list[tuple[Path, dict]] = []
    for f in (_REPO / "data" / "articles").glob("note-*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = d.get("note_url") or d.get("published_url") or d.get("url") or ""
        if not url:
            continue
        if only and only not in d.get("title", ""):
            continue
        if not only:
            pa = (d.get("published_at") or "")[:10]
            if pa != today:
                continue
        out.append((f, d))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="title substring filter (overrides today filter)")
    ap.add_argument(
        "--subjects-json",
        help="optional path to a JSON file mapping title-substring → subject_hint",
    )
    args = ap.parse_args()

    overrides: dict[str, str] = {}
    if args.subjects_json:
        try:
            overrides = json.loads(Path(args.subjects_json).read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("--subjects-json unreadable: %s", exc)
            return 1

    targets = collect_targets(args.only)
    logger.info("targets: %d", len(targets))
    for f, d in targets:
        title = d.get("title", "")
        subject = _pick_subject(title, overrides)
        logger.info("  %s", title[:70])
        logger.info("    subject: %s", subject[:120])

    if not targets:
        logger.warning(
            "no targets — pass --only <title-substring> or publish "
            "articles today first",
        )
        return 0

    if not args.apply:
        logger.info("dry run — pass --apply to generate+swap")
        return 0

    kill_brave()
    from generators.chatgpt_image_generator import ChatGPTImageGenerator
    from publishers.note_publisher import NotePublisher

    img_gen = ChatGPTImageGenerator(headless=False)
    out_dir = _REPO / "data" / "images" / "covers"
    out_dir.mkdir(parents=True, exist_ok=True)

    generated: list[tuple[Path, dict, Path]] = []
    for f, d in targets:
        title = d.get("title", "")
        subject = _pick_subject(title, overrides)
        prompt = _build_prompt(title, subject)
        ts = time.strftime("%Y%m%d_%H%M%S")
        slug = f.stem.replace("note-", "")[:32]
        out_path = out_dir / f"smash_{slug}_{ts}.png"
        logger.info("=" * 70)
        logger.info("generating: %s", title[:70])
        try:
            saved = img_gen.generate(
                prompt=prompt, size="landscape", out_path=out_path,
            )
        except Exception as exc:
            logger.exception("generate raised: %s", exc)
            saved = None
        if not saved or not saved.exists():
            logger.error("FAIL gen: %s", title[:60])
            continue
        d["_cover_image_before_smash"] = d.get("cover_image")
        d["cover_image"] = str(saved.relative_to(_REPO))
        f.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        generated.append((f, d, saved))
        logger.info("OK gen: %s", saved.name)

    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[tuple[str, str]] = []
    try:
        for f, d, cover in generated:
            title = d.get("title", "")
            url = (
                d.get("note_url")
                or d.get("published_url")
                or d.get("url")
            )
            if not url:
                continue
            logger.info("editing eyecatch: %s", url)
            try:
                ok = pub.edit_article(
                    url=url,
                    new_title=title,
                    new_content=d.get("content", "") or "",
                    cover_image_path=str(cover.resolve()),
                )
            except Exception as exc:
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("OK swap: %s", title[:60])
            else:
                failed.append((title, url))
                logger.error("FAIL swap: %s", title[:60])
    finally:
        pub.close()

    logger.info(
        "DONE — generated=%d uploaded=%d failed=%d",
        len(generated), succeeded, len(failed),
    )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
