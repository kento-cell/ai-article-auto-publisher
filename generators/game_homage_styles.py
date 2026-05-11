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
        "fit_hint": (
            "新規参入、デビュー、初登場、新商品リリース、新キャラクター解禁、"
            "新ツール参戦、新機能発表など、新しく登場する話題の記事。"
            "「ついに来た」「待望の」「期待の新人」系。"
        ),
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
        "fit_hint": (
            "意外な発見、隠れた事実、知られざる真実、初遭遇、未知のジャンル、"
            "謎の現象、驚き系。「実は」「知らなかった」「衝撃」「これが噂の」系の記事。"
        ),
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
        "fit_hint": (
            "スキルアップ、成長、ステップアップ、進化、レベルアップ、副業の単価上昇、"
            "実力向上、キャリアアップ、英語学習進捗系。「一段階上の」「上達」「成長」系の記事。"
        ),
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
        "fit_hint": (
            "対立、論破、徹底批判、決着、敗北、勝負、優劣判定、撃破、"
            "失敗事例の分析、危険警告系。「やめろ」「やってはいけない」「終わった」"
            "「これが結論」「優勝」「圧勝」系の記事。"
        ),
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
        "fit_hint": (
            "ゴール達成、完了、修了、卒業、完走、完成、ステージクリア、目標達成。"
            "「ようやくここまで」「やっと終わった」「これで完成」「完結」"
            "「無事達成」系の節目・終わりを祝う記事。"
        ),
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
        "fit_hint": (
            "注意喚起、警告、トラブル、危険性、リスク、詐欺注意、規約違反、"
            "セキュリティ脅威、炎上事件、健康被害、税制リスクなど。"
            "「気をつけろ」「危険」「注意」「警告」「やってはいけない」"
            "「○○の罠」「○○に注意」系の記事。"
        ),
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
        "fit_hint": (
            "始め方ガイド、入門、初心者向け、これから始める人、初回設定、"
            "0から始める、スタートアップ系。「始めよう」「最初の一歩」"
            "「ゼロから」「これから始める」「○○入門」系のチュートリアル/HOW-TO 記事。"
        ),
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
        "fit_hint": (
            "2 つの選択肢の対決、ガチンコ対決、徹底比較、A vs B、"
            "競合製品の対峙、ライバル関係、二択。「○○ vs ○○」「どっち」"
            "「対決」「徹底比較」系のサシ比較記事。"
        ),
        "style_block": (
            "対戦アーケードゲームの試合開始演出風キービジュアル。"
            "赤と青に二分割されたスピードラインの背景。中央には光るVS字。"
            "両側に記事の象徴となる被写体 (主題を構成する2つのシルエット、対比構図) が配置されている。"
            "「READY?」または「FIGHT!」の英字テキストを画面中央上部にゴールド黄色＋黒い縁取りの極太書体で大きく入れる。"
            "色味は赤・青・ゴールド・白・黒の5色基調。スポ根的な熱量。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「FIGHT!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "rhythm_perfect",
        "fit_hint": (
            "完全攻略、全網羅、コンプリート、満点解説、完全ガイド、保存版、決定版、"
            "完璧、ノーミス。「完全ガイド」「全○○まとめ」「決定版」「保存版」"
            "「コンプリート」「網羅」系の網羅的記事。"
        ),
        "style_block": (
            "リズムゲームの判定演出風キービジュアル。"
            "紫〜マゼンタのネオングラデーション背景に、"
            "中央から外へ向かう放射状のスピードラインと音符ノートの軌跡が散らばる。"
            "中央には記事の象徴となる被写体のシルエットが踊る/演奏する動的ポーズで配置。"
            "「PERFECT!!」の英字テキストを画面上部に虹色グラデ＋白の縁取りの極太書体で大きく入れる。"
            "下部にコンボ数表示風の数字 UI 枠 (実数は描かない) を薄く配置。"
            "ネオン色 (シアン・マゼンタ・パープル・イエロー) のグロー、CRT 風スキャンライン。"
            "色味はマゼンタ・パープル・シアン・白の4色基調。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「PERFECT!!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "hunt_success",
        "fit_hint": (
            "目標達成、月収◯万円達成、◯日で結果、稼げた、収益化成功、副業実績、"
            "資格取得、合格。「達成」「成功」「稼げた」「結果出た」「○○円達成」"
            "「副業で月◯万円」系の達成 / 報告系記事。"
        ),
        "style_block": (
            "モンスター討伐型アクションゲームの「狩猟成功!!」演出風キービジュアル。"
            "黄昏のオレンジ〜暗い赤の空に薄雲、地面は岩山シルエット。"
            "中央に記事の象徴となる被写体 (倒した獲物/達成のアイコン) が大きく配置され、"
            "上部に「狩猟成功!!」の和文テキストをゴールド黄色＋濃茶縁取りの極太書体で大きく入れる。"
            "メダル/勲章のアイコンと光の粒子が周囲に散る。"
            "色味はオレンジ・濃茶・ゴールド・白の4色基調。達成感と威厳を強調。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「狩猟成功!!」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "gacha_ssr",
        "fit_hint": (
            "隠れた逸品、知る人ぞ知る、レアな発見、希少、超優良、本物の、究極の。"
            "「隠れた名店」「絶品」「神アイテム」「殿堂入り」「至高の」"
            "「コスパ最強」系のレア発見/推し記事。"
        ),
        "style_block": (
            "ガチャゲームの最高レアリティ排出演出風キービジュアル。"
            "深い紫の背景に、中央から虹色 (赤・橙・黄・緑・青・紫) の七色光線が"
            "外側へ放射状に伸びる派手な構図。"
            "中央には記事の象徴となる被写体のシルエットが封印解除されるように浮かび上がる。"
            "「SSR」の英字テキストを画面上部に巨大なゴールド黄色＋赤縁取りで配置、"
            "周囲に星型の光と金色の粒子が飛び散る。"
            "色味は紫・虹色・ゴールド・白の発色重視。豪華絢爛なお祭り感。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「SSR」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "chapter_opening",
        "fit_hint": (
            "新時代、新章、新パラダイム、2026 年版、最新トレンド、新潮流、変革、"
            "次世代。「新時代」「○○年版」「次世代」「パラダイムシフト」"
            "「これからの○○」系の時代論/トレンド総括記事。"
        ),
        "style_block": (
            "JRPGの章タイトル開幕演出風キービジュアル。"
            "深い濃紺〜黒の夜空背景に、月や星のシルエットが薄く浮かぶ。"
            "画面中央〜下部には記事の象徴となる被写体 (旅立つ後ろ姿のシルエット) を配置。"
            "上部に「第◯章」の和文テキストを白＋金縁取りの細身明朝体で品よく大きく入れる。"
            "(数字部分は描かず「第」と「章」のみ、または「OPENING」の英字代替も可)"
            "下端に細い金色の装飾ライン。"
            "色味は濃紺・黒・白・ゴールドの4色基調。荘厳で静謐な雰囲気、新章の始まりを示唆。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「第◯章」または「OPENING」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "stream_thumbnail",
        "fit_hint": (
            "実体験、やってみた、検証、実況、実演、レビュー、リアル感想。"
            "「やってみた」「実際に試した」「検証してみた」「実演」「○○使ってみた」"
            "「リアル体験」「実況」系の体験談記事。"
        ),
        "style_block": (
            "配信プラットフォームのライブ配信サムネイル風キービジュアル。"
            "鮮やかな赤〜オレンジのグラデーション背景に、巨大な太字テキストが画面の40%を占める。"
            "中央右側に記事の象徴となる被写体 (顔写真/アイコン的シルエット) が配置されている。"
            "「実況」または「LIVE」の和文または英字テキストを画面左上に巨大な白＋黒縁取り＋赤シャドウの極太ゴシック体で入れる。"
            "右下に「!?」マーク、雷形マーク、強調記号などのスタンプ風装飾。"
            "色味は赤・オレンジ・白・黒の4色基調。煽り系YouTuberサムネの強い視覚インパクト。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「実況」/「LIVE」/「!?」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "character_select",
        "fit_hint": (
            "選び方、選択基準、ツール選定、商品比較 (複数選択肢)、ランキング、"
            "おすすめ列挙。「○○の選び方」「おすすめ◯選」「○○ランキング」"
            "「どれを選ぶ」「比較一覧」系の選定/列挙記事 (3 つ以上の選択肢)。"
        ),
        "style_block": (
            "格闘ゲームのキャラクター選択画面風キービジュアル。"
            "暗い金属質の背景に、6〜9 マスのグリッドが画面下半分に並ぶ。"
            "中央のマスのみ強い赤いカーソル枠で囲まれており、その中に記事の象徴となる被写体が配置されている。"
            "他のマスにはぼやけたシルエットが薄く配置される。"
            "上部に「SELECT」の英字テキストをシアン色＋白の縁取りの極太書体で大きく入れる。"
            "周囲に CRT スキャンライン、ホログラム風のグリッチノイズ。"
            "色味は黒・金属グレー・赤・シアンの4色基調。選定の重みと近未来感。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「SELECT」のみ、それ以外の文字は描かない。"
        ),
    },
    {
        "name": "event_banner",
        "fit_hint": (
            "速報、緊急情報、期間限定、今だけ、新情報、開催中、ライブ更新、"
            "本日付情報。「速報」「緊急」「期間限定」「今だけ」「開催!!」"
            "「速攻まとめ」系のタイムリー / 鮮度重視記事。"
        ),
        "style_block": (
            "ソーシャルゲームの期間限定イベント告知バナー風キービジュアル。"
            "鮮やかな水色〜ピンクの光沢グラデーション背景に、画面いっぱいの星型・キラキラエフェクト。"
            "中央に記事の象徴となる被写体 (キービジュアル/メイン要素) を堂々と配置し、"
            "上部に「期間限定」の和文テキストをゴールド黄色＋赤い縁取りの極太書体で入れ、"
            "下部に「開催!」のテキストを白＋紺の縁取りで添える。"
            "周囲にリボン装飾と星マーク、画面左右にカウントダウン風の枠 (数字は描かない)。"
            "色味は水色・ピンク・ゴールド・白の4色基調。お祭り感あるポップな装飾過多デザイン。"
            "16:9 横長 (1792×1024 ピクセル)。テキストは「期間限定」「開催!」のみ、それ以外の文字は描かない。"
        ),
    },
]


def _pick_style_by_rag(title: str, content_excerpt: str = "") -> dict | None:
    """RAG-driven style picker (2026-05-11).

    Queries the `thumbnail_styles` chromadb collection with the article's
    title + content excerpt and returns the style whose fit_hint scores
    highest. Returns None when:
      - chromadb / sentence-transformers not installed, OR
      - `thumbnail_styles` collection not built, OR
      - retrieval fails for any reason

    Caller falls back to SHA-256 deterministic pick on None.
    """
    if os.environ.get("STYLE_SELECT_MODE", "rag").lower() not in (
        "rag", "auto", "semantic",
    ):
        return None
    try:
        from generators.rag_retriever import RagRetriever
    except ImportError:
        return None
    try:
        retriever = RagRetriever()
        # Use title + first 600 chars of content so 「副業 月5万達成
        # ロードマップ」 style hints map to hunt_success / quest_start
        # at semantic level instead of literal-word match.
        query = (title.strip() + "\n" + (content_excerpt or "").strip())[:1500]
        hits = retriever.retrieve(
            query=query,
            collection="thumbnail_styles",
            top_k=3,
            score_threshold=0.50,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("RAG style pick failed: %s", exc)
        return None
    if not hits:
        return None
    # The top hit's metadata.section_title is the style name.
    top_style_name = hits[0].metadata.get("section_title", "") if hits[0].metadata else ""
    if not top_style_name:
        return None
    for s in _STYLES:
        if s["name"] == top_style_name:
            logger.info(
                "RAG style pick for title=%r → %s (sim %.3f)",
                title[:40], s["name"], hits[0].score,
            )
            return s
    return None


def pick_style_for_article(title: str, content_excerpt: str = "") -> dict:
    """Pick one game-homage style for *title*.

    Strategy (2026-05-11):
    1. Try RAG-based semantic pick against `thumbnail_styles` collection
       — yields content-aware selection (副業達成 → hunt_success,
       比較記事 → ready_fight, etc.).
    2. Fall back to SHA-256(title) deterministic pick when RAG is
       unavailable or no hit clears the threshold.

    Both branches are deterministic on the same title+content so
    regenerations of the same article keep the same style — important
    for visual consistency across cover + inline images.
    """
    rag_choice = _pick_style_by_rag(title, content_excerpt)
    if rag_choice is not None:
        return rag_choice
    h = hashlib.sha256(title.encode("utf-8")).digest()
    idx = h[0] % len(_STYLES)
    chosen = _STYLES[idx]
    logger.info(
        "game-homage style (SHA-256 fallback) for title=%r → %s",
        title[:40], chosen["name"],
    )
    return chosen


def is_game_homage_enabled() -> bool:
    """``IMAGE_STYLE_PACK`` env toggle — defaults to ``ghibli``."""
    return os.environ.get("IMAGE_STYLE_PACK", "").strip().lower() == "game_homage"


def list_styles() -> list[str]:
    return [s["name"] for s in _STYLES]
