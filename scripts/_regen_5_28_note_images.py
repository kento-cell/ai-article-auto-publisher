"""Regenerate cover + inline images for the 4 note articles published on
2026-05-28 morning that fell back to Unsplash, using ChatGPT.

Per user request 2026-05-28: K-beauty / Korean-cosmetic articles get
photo-realistic editorial-poster styling (K-Beauty magazine aesthetic,
not the default Ghibli watercolor). The other two articles use the
standard pipeline (infographic cover + Ghibli inline).

The morning publish round failed every ChatGPT batch because Brave's
CDP port wasn't open AND launch_persistent_context died at startup
(exitCode=21, user_data_dir lock vs the user's Brave window). This
script therefore launches Brave in CDP mode itself (allow_launch=True)
so the attach path is available even when AUTO_LAUNCH_BRAVE_CDP=0 in
.env (user-controlled default).

Targets and routing:
  - kc_004 (韓国コスメ買える 4 経路) → poster_batch
  - kb_007 (韓国コスメ起因 肌トラブル 5)  → poster_batch
  - sl_003 (1週間持ち物減)            → standard chatgpt_image_batch
  - Tech CEOs AI psychosis            → standard chatgpt_image_batch

For the poster route we bypass the infographic-banner cover template by
swapping ChatGPTImageGenerator._build_prompt with a poster variant for
the duration of that article's batch, then restore the original. We do
NOT monkey-patch globally because the standard articles still want the
infographic cover.
"""
from __future__ import annotations

import json
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("regen_5_28_note")


TARGETS = [
    # (article_id, route)
    ("note-日本で韓国コスメを買える_4_経路__O-d9e7d6f0", "poster"),
    ("note-韓国コスメ起因の肌トラブル_5_パターン-6abb9880", "poster"),
    ("note-1週間で持ち物を1-2割減らせる_丁寧な-1406264b", "standard"),
    ("note-Tech_CEOs_are_appare-e403776c", "standard"),
]


def _ensure_brave_cdp() -> bool:
    from generators.chatgpt_batch_helper import ensure_brave_cdp_listening
    port = int(os.environ.get("CHATGPT_CDP_PORT", "9222"))
    # allow_launch=True forces a Brave kill+relaunch when the port is
    # cold — user explicitly asked for ChatGPT regen so accepting the
    # disruption is in-scope here.
    return ensure_brave_cdp_listening(port, allow_launch=True, timeout=20.0)


def _poster_build_prompt(
    prompt: str,
    size,
    is_cover: bool = False,
    style_block: str | None = None,
) -> str:
    """Drop-in replacement for ChatGPTImageGenerator._build_prompt that
    forces a realistic K-Beauty magazine-poster style for BOTH cover
    and inline. Bypasses the infographic-banner cover template."""
    from generators.chatgpt_image_generator import _SIZE_PHRASE
    kind = "サムネイル画像" if is_cover else "インライン画像"
    size_phrase = _SIZE_PHRASE[size]
    return (
        f"【最重要】このメッセージで全情報を提供しています。"
        f"即座に画像を1枚生成してください。"
        f"テンプレ確認・項目の聞き返し・追加質問は禁止。\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"用途: note記事の{kind} (1枚)\n"
        f"サイズ: {size_phrase}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"描いてほしいシーン:\n{prompt}\n\n"
        f"【スタイル指定 — 韓国美容雑誌 / K-Beauty ポスター調】\n"
        f"- 韓国の美容雑誌 (Vogue Korea, Allure Korea, Marie Claire Korea) "
        f"の編集ページのような実写エディトリアル写真\n"
        f"- 高解像度のグロッシーな雑誌表紙 / ポスター質感\n"
        f"- 韓国モデル (20代女性、ナチュラルメイク、グラスキン透明肌) "
        f"または韓国コスメの製品 (ボトル・チューブ・パッド・パッケージ) が主役\n"
        f"- ソフトな自然光、淡いピンク / クリーム / ベージュ / パールホワイト / "
        f"ミルキーローズ のパステルパレット\n"
        f"- 雑誌表紙のような余白、中央〜オフセンター構図、ミニマル整然\n"
        f"- 小道具: 化粧鏡 / 花びら / 大理石 / シルクの布 / 韓国カフェの陽光 など\n\n"
        f"【絶対禁止】\n"
        f"- アニメ・水彩・3D CGI・イラスト・漫画・落書き・ピクセルアート "
        f"(すべて NG。あくまで実写写真風)\n"
        f"- テキスト・読める文字・ロゴ・透かし・UI スクリーンショット\n"
        f"- 実在ブランドの商標ロゴ "
        f"(ボトルはジェネリックなパッケージに置き換え可)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"出力は実写写真風ポスター画像 1 枚のみ。"
        f"前置き・後置き・質問・テンプレ要求は一切禁止。"
    )


def _drop_local_image_md(content: str) -> str:
    """Remove ``![alt](data/images/...)`` markdown so edit_article's
    inline_image_paths route re-uploads fresh ones via note CDN
    (per project_note_inline_image_flow memory: _drop_local_images +
    inline_image_paths is the verified-correct path)."""
    return re.sub(
        r"\n?!\[[^\]]*\]\(data/images/[^)\s]+(?:\s+\"[^\"]*\")?\)\n?",
        "\n",
        content,
    )


def _extract_h2_sections(content: str, limit: int) -> list[str]:
    """Pull up to ``limit`` H2 heading titles from the article body."""
    out: list[str] = []
    for m in re.finditer(r"^##\s+(.+?)\s*$", content, flags=re.MULTILINE):
        t = m.group(1).strip()
        if t and not t.startswith("#"):
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _poster_batch(
    title: str,
    content: str,
    inline_count: int,
    slug_hint: str,
) -> tuple[Path | None, list[Path]]:
    """Run a ChatGPT image batch with K-Beauty poster style for ALL
    slots (cover + inline). Bypasses chatgpt_image_batch so the
    monkey-patch is scoped to this call only."""
    from generators.chatgpt_image_generator import ChatGPTImageGenerator
    from generators.visual_prompt_builder import build_visual_prompt

    # Build per-slot scene descriptions. First slot = cover (whole-
    # article visual), rest = inline (one per H2 section).
    sections = _extract_h2_sections(content, inline_count)
    while len(sections) < inline_count:
        sections.append(title)
    cover_brief = build_visual_prompt(
        title=title, section=None,
        genre_hint="K-beauty / Korean cosmetics editorial",
    )
    inline_briefs = [
        build_visual_prompt(
            title=title, section=s,
            genre_hint="K-beauty / Korean cosmetics editorial",
        )
        for s in sections
    ]
    prompts = [cover_brief] + inline_briefs
    out_dir = _REPO / "data" / "images" / "covers"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug_hint)[:40]
    out_paths = [
        out_dir / f"poster_{safe_slug}_{ts}_{i:02d}.png"
        for i in range(len(prompts))
    ]

    gen = ChatGPTImageGenerator(headless=False)
    # Swap _build_prompt only for this batch. ChatGPTImageGenerator is
    # a single instance per call so the patch stays local to this run.
    # Use __dict__ to retrieve the original staticmethod *descriptor*
    # (attribute access unwraps it to a plain function, and reassigning
    # that bare function turns it back into an instance method — then
    # ``self`` slips in as positional arg 1 on the next call and breaks
    # every later standard-route batch with "multiple values for
    # 'is_cover'").
    original_build = ChatGPTImageGenerator.__dict__["_build_prompt"]
    ChatGPTImageGenerator._build_prompt = staticmethod(_poster_build_prompt)
    try:
        results = gen.generate_batch(
            prompts=prompts,
            size="landscape",
            out_paths=out_paths,
            topic=f"K-beauty editorial: {title[:60]}",
        )
    finally:
        ChatGPTImageGenerator._build_prompt = original_build
        try:
            gen.close()
        except Exception:  # noqa: BLE001
            pass

    cover_p = results[0] if results else None
    inlines_p = [p for p in (results[1:] if len(results) > 1 else []) if p]
    return cover_p, inlines_p


def _standard_batch(
    title: str,
    content: str,
    inline_count: int,
    slug_hint: str,
) -> tuple[Path | None, list[Path]]:
    from generators.chatgpt_batch_helper import chatgpt_image_batch
    return chatgpt_image_batch(
        title=title,
        content=content,
        inline_count=inline_count,
        slug_hint=slug_hint,
        genre_hint="general tech / lifestyle",
    )


def main() -> int:
    if not _ensure_brave_cdp():
        logger.error(
            "Brave CDP unavailable — aborting "
            "(run launch_brave_cdp.bat manually)",
        )
        return 1

    from generators.chatgpt_batch_helper import is_chatgpt_image_gen_enabled
    if not is_chatgpt_image_gen_enabled():
        logger.error(
            "ChatGPT image gen disabled (USE_CHATGPT_IMAGES=0). "
            "Set it to 1 in .env or unset.",
        )
        return 1

    from publishers.note_publisher import NotePublisher

    articles_dir = _REPO / "data" / "articles"
    jobs: list[dict] = []
    for aid, route in TARGETS:
        path = articles_dir / f"{aid}.json"
        if not path.exists():
            logger.warning("missing store entry: %s", aid)
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        url = d.get("published_url") or d.get("note_url") or d.get("url")
        if not url:
            logger.warning("no URL stored for %s — skipping", aid)
            continue
        jobs.append({
            "aid": aid,
            "route": route,
            "path": path,
            "data": d,
            "title": d.get("title", ""),
            "content": d.get("content", ""),
            "url": url,
        })

    logger.info("targets: %d (poster=%d standard=%d)",
                len(jobs),
                sum(1 for j in jobs if j["route"] == "poster"),
                sum(1 for j in jobs if j["route"] == "standard"))

    # ----- Phase 1: generate images -----
    for j in jobs:
        logger.info("=" * 70)
        logger.info("[%s] %s", j["route"], j["title"][:60])
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", j["aid"])[:40]
        try:
            if j["route"] == "poster":
                cover, inlines = _poster_batch(
                    title=j["title"], content=j["content"],
                    inline_count=4, slug_hint=f"regen_{slug}",
                )
            else:
                cover, inlines = _standard_batch(
                    title=j["title"], content=j["content"],
                    inline_count=4, slug_hint=f"regen_{slug}",
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("image batch raised: %s", exc)
            cover, inlines = None, []
        j["cover"] = cover
        j["inlines"] = list(inlines or [])
        logger.info("  → cover=%s inlines=%d",
                    bool(cover), len(j["inlines"]))

        if cover or j["inlines"]:
            try:
                j["data"]["_cover_image_before_regen_5_28"] = (
                    j["data"].get("cover_image")
                )
                j["data"]["_inline_images_before_regen_5_28"] = (
                    j["data"].get("inline_images")
                )
                if cover:
                    j["data"]["cover_image"] = str(cover.relative_to(_REPO))
                j["data"]["inline_images"] = [
                    str(p.relative_to(_REPO)) for p in j["inlines"]
                ]
                j["path"].write_text(
                    json.dumps(j["data"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("store write failed for %s: %s",
                               j["aid"], exc)

    # ----- Phase 2: upload via edit_article -----
    pub = NotePublisher(headless=False)
    succeeded = 0
    failed: list[str] = []
    try:
        for j in jobs:
            if not j.get("cover") and not j.get("inlines"):
                logger.warning("skip %s (no images generated)",
                               j["title"][:40])
                failed.append(j["title"])
                continue
            body = _drop_local_image_md(j["content"]) if j["content"] else None
            logger.info("Editing: %s", j["url"])
            try:
                ok = pub.edit_article(
                    url=j["url"],
                    new_title=None,
                    new_content=body,
                    inline_image_paths=[
                        str(p.resolve()) for p in j.get("inlines", [])
                    ] or None,
                    cover_image_path=(
                        str(j["cover"].resolve())
                        if j.get("cover") else None
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("edit_article raised: %s", exc)
                ok = False
            if ok:
                succeeded += 1
                logger.info("  OK: %s", j["title"][:60])
            else:
                failed.append(j["title"])
                logger.error("  FAIL: %s", j["title"][:60])
            time.sleep(4)
    finally:
        pub.close()

    logger.info(
        "DONE — generated=%d uploaded=%d failed=%d",
        sum(1 for j in jobs if j.get("cover") or j.get("inlines")),
        succeeded,
        len(failed),
    )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
