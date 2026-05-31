"""Named image-style presets for the ChatGPT image pipeline.

A *preset* bundles two things:

* ``style_block`` — the style text injected into inline prompts (and into
  the cover prompt when ``cover_styled`` is set).
* ``cover_styled`` — when True the cover uses ``style_block`` via the
  generic styled-cover template instead of the default click-bait
  infographic banner that ``ChatGPTImageGenerator._build_prompt`` emits
  for ``is_cover``.

This replaces the per-batch monkey-patch of
``ChatGPTImageGenerator._build_prompt`` that the K-Beauty poster route
used (see ``scripts/_regen_5_28_note_images.py`` history and STATE
Next Action "poster route 汎用化"). Callers now pass
``style_preset="kbeauty_poster"`` to
:func:`generators.chatgpt_batch_helper.chatgpt_image_batch` instead of
swapping a staticmethod descriptor at runtime.
"""
from __future__ import annotations

from typing import Final, Optional, TypedDict


class StylePreset(TypedDict):
    """One named image style.

    cover_styled: True → the cover image is built from ``style_block``
        (photo/editorial look) rather than the infographic-banner cover
        template. False → only inline images use ``style_block``; the
        cover keeps the default click-bait infographic banner.
    style_block: style directive injected into the prompt(s).
    """

    cover_styled: bool
    style_block: str


# K-Beauty editorial magazine poster. Forces a photo-realistic Korean
# beauty-magazine look for BOTH cover and inline (cover_styled=True) so a
# K-beauty / Korean-cosmetics article reads as a glossy editorial set
# rather than the default anime-watercolor + infographic banner combo.
# The anti-anime / no-trademark constraints live here because they are
# style-specific (the generic styled-cover template only forbids
# text/logos/watermarks).
_KBEAUTY_POSTER_STYLE: Final[str] = (
    "韓国美容雑誌 / K-Beauty ポスター調:\n"
    "- 韓国の美容雑誌 (Vogue Korea, Allure Korea, Marie Claire Korea) "
    "の編集ページのような実写エディトリアル写真\n"
    "- 高解像度のグロッシーな雑誌表紙 / ポスター質感\n"
    "- 韓国モデル (20代女性、ナチュラルメイク、グラスキン透明肌) "
    "または韓国コスメの製品 (ボトル・チューブ・パッド・パッケージ) が主役\n"
    "- ソフトな自然光、淡いピンク / クリーム / ベージュ / パールホワイト / "
    "ミルキーローズ のパステルパレット\n"
    "- 雑誌表紙のような余白、中央〜オフセンター構図、ミニマル整然\n"
    "- 小道具: 化粧鏡 / 花びら / 大理石 / シルクの布 / 韓国カフェの陽光 など\n"
    "- あくまで実写写真風。アニメ・水彩・3D CGI・イラスト・漫画・"
    "落書き・ピクセルアートは禁止\n"
    "- 実在ブランドの商標ロゴは描かない (ジェネリックなパッケージに置き換え)"
)


PRESETS: Final[dict[str, StylePreset]] = {
    "kbeauty_poster": {
        "cover_styled": True,
        "style_block": _KBEAUTY_POSTER_STYLE,
    },
}


def get_preset(name: Optional[str]) -> Optional[StylePreset]:
    """Resolve a preset by name. Returns ``None`` for an empty/unknown
    name so callers fall back to their default (game-homage / ghibli)
    style selection."""
    if not name:
        return None
    return PRESETS.get(name)
