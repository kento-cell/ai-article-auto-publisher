"""Game-homage thumbnail style pack.

When `IMAGE_STYLE_PACK=game_homage` is set in the environment (or
caller passes ``style_pack="game_homage"`` directly), the ChatGPT
image pipeline picks ONE of these styles per article, applies it
to the cover AND every inline image so a single article reads as
a coherent visual set.

Selection is **deterministic by SHA-256 of the article title** so:
  * The same article re-running picks the same style (idempotent)
  * Different articles are spread across the pool

Each style is described by visual idiom only — no franchise names —
to stay clear of trademark issues. ChatGPT often re-interprets the
prompt anyway; the user has confirmed (memory:
feedback_thumbnail_style_preference.md) that content-match matters
more than strict style compliance.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Final

logger = logging.getLogger(__name__)


# Each entry: { name, cover_subject_hint_template, style_block }
# - cover_subject_hint_template: optional {title} placeholder. Used
#   only as a hint to the model — ChatGPT may still freelance.
# - style_block: full Japanese style instructions inserted into the
#   ChatGPT prompt's 【スタイル】 section. Should describe the visual
#   idiom thoroughly enough that the model produces a consistent set
#   of cover + inline images for one article.
_STYLES: Final[list[dict]] = [
    {
        "name": "fighting_announce",
        "style_block": (
            "格闘ゲームの新キャラクター参戦発表風キービジュアル。"
            "シアン (鮮やかな青〜白の光) のスピード感あるグラデーション背景に、"
            "画面手前へ飛び散る黒い墨スプラッシュが大胆に配置されている。"
            "中央には記事の象徴となる被写体のシルエットが堂々と立ち、"
            "左下には極太のゴールド黄色＋赤い縁取りで「参戦!!」の日本語テキストを大きく入れる。"
            "レトロアニメの予告編のような迫力と勢いを最優先。"
            "光のラインや風の跡で前進感を強調。色味は黒・シアン・ゴールド黄・白の4色基調。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「参戦!!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "monster_appeared",
        "style_block": (
            "対戦型モンスター育成RPGの野生モンスター遭遇シーン風キービジュアル。"
            "緑〜深い青の草原や森の背景に、白い吹き出し風の枠と「あらわれた!」の日本語テキストを"
            "ゴールド黄色＋赤い縁取りの極太書体で右上に配置。"
            "中央には記事の象徴となる被写体のシルエット (ピクセル風モンスター調) を配置。"
            "16ビット〜32ビットRPG風のドット絵テクスチャを背景に重ね、レトロゲーム機の画面風の"
            "黒枠を四隅に薄く付ける。色味は緑・白・ゴールド・黒の4色基調。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「あらわれた!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "rpg_level_up",
        "style_block": (
            "ファンタジーRPGのレベルアップ演出風キービジュアル。"
            "暗紺色〜紫の星空背景に、中央から金色の光線が放射状に伸びる構図。"
            "中央には記事の象徴となる被写体のシルエット (勇者ポーズ風) が下から上へ飛び上がっている。"
            "「LEVEL UP!」の英語テキストをゴールド黄色＋赤い縁取りの極太書体で上部に大きく入れる。"
            "周囲に光の粒子・星・上昇する英数字が散らばる。色味は紫・紺・ゴールド・白の4色基調。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「LEVEL UP!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "fighting_ko",
        "style_block": (
            "対戦格闘ゲームの決着画面 (K.O. 演出) 風キービジュアル。"
            "赤〜オレンジの放射状グラデーション背景に、中央から外へ向かって白い衝撃波が広がる。"
            "中央には記事の象徴となる被写体のシルエットが拳を振り抜くポーズで配置されている。"
            "「K.O.!!」の英字テキストを巨大なゴールド黄色＋黒い縁取りの極太書体で画面中央に重ねる。"
            "画面の四隅に火花エフェクトと黒い斑点。色味は赤・オレンジ・ゴールド・黒・白の5色基調。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「K.O.!!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "stage_clear",
        "style_block": (
            "プラットフォーマー2Dアクションゲームのステージクリア演出風キービジュアル。"
            "明るい水色〜白の空背景に、紙吹雪と星型の光が舞う。"
            "中央には記事の象徴となる被写体のシルエット (ジャンプ・ガッツポーズ) が配置され、"
            "「STAGE CLEAR!」の英字テキストを画面上部にゴールド黄色＋赤い縁取りの極太書体で大きく入れる。"
            "下部にスコア表示風の数字パネル (実際の数値は描かず、UI枠だけ) を薄く配置。"
            "色味は水色・白・ゴールド・赤の4色基調。明るくお祝いムード。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「STAGE CLEAR!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "warning_alert",
        "style_block": (
            "8〜16ビット時代のロボットアクションゲームのボス出現警告画面風キービジュアル。"
            "黒背景に黄色と黒の斜めストライプ警告帯が画面上下を横切る。"
            "中央には記事の象徴となる被写体のシルエット (ボスキャラ風) が立ち、"
            "「WARNING!」の英字テキストを赤色の極太書体で画面中央に大きく重ねる。"
            "周囲にCRT スキャンライン・ピクセルノイズ・赤い点滅エフェクト。"
            "色味は黒・黄色・赤・白の4色基調。緊張感とレトロな質感を強調。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「WARNING!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "quest_start",
        "style_block": (
            "オープンワールドRPGのクエスト開始通知風キービジュアル。"
            "古びた羊皮紙風の背景に、ファンタジー風の装飾枠 (ツタ・剣・盾) が縁を縁取る。"
            "中央には記事の象徴となる被写体 (記事のテーマを表すアイコン的シルエット) が配置され、"
            "上部に「QUEST START」の英字テキストをゴールド黄色＋濃い茶色の縁取りで大きく入れる。"
            "光の粒子と古地図の質感を背景に重ねる。色味はベージュ・ゴールド・濃茶・深紅の4色基調。"
            "中世RPGの威厳ある雰囲気。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「QUEST START」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "ready_fight",
        "style_block": (
            "対戦アーケードゲームの試合開始演出風キービジュアル。"
            "赤と青に二分割されたスピードラインの背景。中央には光るVS字。"
            "両側に記事の象徴となる被写体 (主題を構成する2つのシルエット、対比構図) が配置されている。"
            "「READY?」または「FIGHT!」の英字テキストを画面中央上部にゴールド黄色＋黒い縁取りの極太書体で大きく入れる。"
            "色味は赤・青・ゴールド・白・黒の5色基調。スポ根的な熱量。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「FIGHT!」のみ、それ以外の文字は描かない。"
        ),
    },
]


def pick_style_for_article(title: str) -> dict:
    """Deterministically pick one game-homage style for *title*.

    SHA-256 keyed so retries / regenerations of the same article
    pick the same style — important because all inline images for
    one article must share the visual idiom for the set to read as
    coherent.
    """
    h = hashlib.sha256(title.encode("utf-8")).digest()
    idx = h[0] % len(_STYLES)
    chosen = _STYLES[idx]
    logger.info(
        "game-homage style for title=%r → %s",
        title[:40], chosen["name"],
    )
    return chosen


def is_game_homage_enabled() -> bool:
    """``IMAGE_STYLE_PACK`` env toggle — defaults to ``ghibli``."""
    return os.environ.get("IMAGE_STYLE_PACK", "").strip().lower() == "game_homage"


def list_styles() -> list[str]:
    return [s["name"] for s in _STYLES]
