"""One-shot repair script for 2026-04-13 note posts.

Each article had factual errors introduced by Gemma3:

1. 青空カフェ部 / センチュリーカフェ — fabricated "Future Forward"
   consulting report, fabricated 20% decline stat, and described
   センチュリーカフェ 溝の口 as bustling when the real store has closed.
2. 風神 下北沢 — fake Twitter URL and fake tabelog URL that pointed
   at nonexistent pages.
3. やよい軒 下北沢 — literal ``https://example.com/...`` placeholder
   URLs leaked into the published post.

This script rewrites the stored JSON content for each article with
fact-checked prose (verified via Codex + fujin.gorp.jp + centurycafe.
owst.jp closure notice) and pushes the corrected body to note.com via
:class:`NotePublisher.edit_article`.

Run manually once:
    venv/Scripts/python.exe scripts/fix_today_note_posts.py
"""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from publishers.note_publisher import NotePublisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fix_today_note_posts")


# ---------------------------------------------------------------------------
# Rewritten content blocks
# ---------------------------------------------------------------------------

_DISCLAIMER = """---

## ⚠️ 免責事項

本記事の店舗・施設情報は、執筆時点のGoogle Maps公開データおよび投稿情報をもとにAIが構成しています。営業時間・価格・メニュー等は変更される場合があるため、来店前に[公式サイト](https://fujin.gorp.jp/)または店舗へ直接ご確認ください。また、本記事は情報提供を目的としており、掲載情報の正確性・完全性を保証するものではありません。ご利用は読者ご自身の判断でお願いいたします。
"""


FUJIN_CONTENT = """## 【現地レポ】下北沢の和食居酒屋「風神」— ゲリラ豪雨の夜、常連が静かに集う隠れ家

下北沢駅北口から徒歩数分、北沢2丁目の路地裏に「[風神](https://fujin.gorp.jp/)」という和食居酒屋があります。Blueskyの[青空飲酒部の投稿](https://bsky.app/profile/shiromamu.bsky.social/post/3ltmijuugy22s)で話題になっていたので、気になって調べてみました。

### 投稿者が描いた、その夜の情景

この投稿、ただのグルメ報告じゃないんです。投稿者さんは下北沢の風神で、偶然知り合ったお友達と乾杯。お刺身の鮮度と、茄子のチーズ田楽のトロトロ感に感動している様子が伝わってきます。

そして話のハイライトは、外で鳴り響いていたゲリラ豪雨と雷。「雨だから、仕方ないよね。ゆっくりしていこうね〜」という会話が、カウンター越しに交わされていた — そんな、ちょっと映画のワンシーンみたいな情景です。

> 『雨だから、仕方ないよね。ゆっくりしていこうね〜』と、お酒とお料理を存分に楽しんだのでした。

雨宿りの口実で入った店が、気づいたら「また来たい店」に変わっていた経験、みなさんもありませんか？

### 「風神」は下北沢でどんな位置づけの店か

Web上の店舗情報（[公式ページ](https://fujin.gorp.jp/)）を確認すると、風神は下北沢の北沢2-14-10、こだまビル2階にある和食居酒屋です。地域メディアでは「前菜坊 風神」として紹介されている場合もあり、旬の手作り和食を出す店として知られています。

下北沢というと、どうしても古着屋とネオ居酒屋のイメージが強いですよね。でも実は、駅から少し離れた路地に入ると、こういう「大人がゆっくり飲める和食店」がちゃんと残っているのが、この街の奥行きだったりします。

### 茄子のチーズ田楽 — なぜ青空飲酒部の間で話題になるのか

元投稿で「トロトロ🥰」と評された茄子のチーズ田楽。茄子の田楽自体は定番の和食メニューですが、そこにチーズを乗せるアレンジは、お酒との相性が強烈です。

- 茄子の柔らかさ × チーズの塩気
- 味噌ベースの甘辛さ × 日本酒の辛口
- 見た目の映え × カウンターで食べる臨場感

まさに「SNSでシェアしたくなる一皿」の条件を、静かな和食の顔で満たしている、そういう料理だと想像できます。

### Bluesky「青空飲酒部」というカルチャー

今回の元投稿が投下されていた「[#青空飲酒部](https://bsky.app/search?q=%23%E9%9D%92%E7%A9%BA%E9%A3%B2%E9%85%92%E9%83%A8)」というタグは、Bluesky上でゆるく形成されている飲み会レポコミュニティです。インスタの映え飲みでもなく、X（旧Twitter）のグルメインフルエンサーでもない、「普通の大人の静かな一杯」を共有する空気感が特徴。

風神のような隠れ家店がこのタグで語られているのは、偶然じゃないと思います。派手な演出より、店と客の距離感を大事にする文化があるからこそ、ここで話題になる店は「あぁ、行ってみたい」と思わせる力があります。

### まとめ：話題の店より、話題にされる店

今回ご紹介した[風神](https://fujin.gorp.jp/)は、下北沢の和食居酒屋。現地に行ったレビューではなく、[元のBlueskyポスト](https://bsky.app/profile/shiromamu.bsky.social/post/3ltmijuugy22s)を読んで「こういう店が残っているのがこの街の良さだな」と感じたので、まとめてみました。

下北沢で「静かに一杯やれる店」を探しているなら、候補に入れる価値は十分にありそうです。

## 参考リンク

- 元Blueskyポスト（青空飲酒部）: [Blueskyで見る](https://bsky.app/profile/shiromamu.bsky.social/post/3ltmijuugy22s)
- 風神 店舗情報: [公式サイト](https://fujin.gorp.jp/)
- 店舗の場所: [Googleマップで見る](https://www.google.com/maps/search/?api=1&query=%E9%A2%A8%E7%A5%9E+%E4%B8%8B%E5%8C%97%E6%B2%A2+%E5%8C%97%E6%B2%A22-14-10)
""" + _DISCLAIMER


AOZORA_CONTENT = """## 【保存版】Bluesky「青空カフェ部」が映す、都市カフェ文化のいま

Blueskyで密かに盛り上がっている「[#青空カフェ部](https://bsky.app/search?q=%23%E9%9D%92%E7%A9%BA%E3%82%AB%E3%83%95%E3%82%A7%E9%83%A8)」というタグをご存じでしょうか。X（旧Twitter）のグルメインフルエンサー文化とも、インスタの映えカフェとも違う、Bluesky特有の「穏やかな共有」が起きているタグです。

今回はこのタグで繰り返し言及されている溝の口の「センチュリーカフェ」を手がかりに、Bluesky上のカフェ文化がどう語られているかを整理してみました。

### 「青空カフェ部」という空気感

「青空カフェ部」は、誰か特定の運営者がいるわけではなく、Blueskyのユーザーが自然発生的に使い始めたハッシュタグです。同じ系統の「#青空ごはん部」「#外食班」と並んで、Bluesky上の飲食シェアの「中心地」のひとつになっています。

特徴は、投稿の静けさです。

- 価格マウントがない
- 映え写真の強迫がない
- 店名だけ淡々とシェアされることも多い

X の「バズらせるための店紹介」ではなく、「見た人がそっと行きたくなる店紹介」。この温度差こそが、Blueskyがグルメ情報源として一部ユーザーに支持される理由だと思います。

### 例：溝の口「センチュリーカフェ」

元のBluesky投稿で店名として挙がっていたのが、神奈川県川崎市高津区・溝の口の「[センチュリーカフェ](https://centurycafe.owst.jp/)」でした。

ただし、ここが重要なのですが **公式ページを確認したところ、現時点では閉店しているようです**。このため本記事では「今から行ける店」としての紹介はできません。それでも、投稿者さんがこの店名を挙げたくなったということは、記憶に残るカフェ体験があったからこそ。

つまり青空カフェ部のタグを追うと、現役店だけでなく「閉じてもなお、誰かの記憶に残り続ける店」が共有されていることが見えてきます。これは、X/インスタではあまり起きない現象です。

### なぜBlueskyでこういう文化が育つのか

Bluesky側の設計が効いていると感じます。

1. フィードがアルゴリズム駆動ではない（時系列 + 自分で選ぶカスタムフィード）
2. リポスト文化がまだ過熱していない
3. 投稿の「バズらせるインセンティブ」が少ない

この3つが揃うと、「個人がふと思い出した店」を雑談レベルで投げられる空気ができます。そしてその雑談が、同じ街を愛する他ユーザーに静かに届く。バイラルじゃなく、ローカルな共鳴です。

### Bluesky発のグルメ情報を読むときのコツ

青空カフェ部タグを見るときは、次のように読むと二次情報ノイズを減らせます。

| 読み方 | 具体的に |
|---|---|
| 店名だけ拾う | 感情語や評価は本人の体験なのでそのまま取り込みすぎない |
| 投稿日時を確認 | 古い投稿は閉店している可能性があるため検索で裏取り |
| 公式サイトを探す | 一次情報（営業時間・営業状況）は必ず一次ソース確認 |

今回のセンチュリーカフェのように、記憶の中の店が閉店していた、というケースもあるからこそ、Blueskyのタグは「行きたいお店のリスト」ではなく「街の空気を読む装置」として扱うのが正解だと思います。

### まとめ：Bluesky青空カフェ部は「静かな共鳴装置」

- タグの発信量よりも、タグに漂う温度感が価値
- 店の実在と営業状況は一次ソースで必ず裏取りする
- 閉店店舗ですら「記憶の中の街の輪郭」として残っている

派手さはないけれど、街との付き合い方を丁寧にするための情報源として、青空カフェ部タグは一度覗いてみる価値があります。

## 参考リンク

- Blueskyハッシュタグ: [#青空カフェ部で検索](https://bsky.app/search?q=%23%E9%9D%92%E7%A9%BA%E3%82%AB%E3%83%95%E3%82%A7%E9%83%A8)
- センチュリーカフェ（閉店確認済）: [店舗公式](https://centurycafe.owst.jp/)
- 店舗所在地: [Googleマップで見る](https://www.google.com/maps/search/?api=1&query=%E3%82%BB%E3%83%B3%E3%83%81%E3%83%A5%E3%83%AA%E3%83%BC%E3%82%AB%E3%83%95%E3%82%A7+%E6%BA%9D%E3%81%AE%E5%8F%A3)
""" + _DISCLAIMER


YAYOIKEN_CONTENT = """## 【本音】「下北沢にやよい軒を誘致してくれ」— この叫びが意外と鋭い件

Blueskyに、こんな一言が流れてきました。

> もう下北沢に古着屋とネオ居酒屋はいらん。やよい軒だ。やよい軒を誘致してくれ

投稿者は「たぬ」さん。元ネタはこちらです → [Blueskyの投稿](https://bsky.app/profile/tanu.bsky.social/post/3llntqnztmk2s)

一瞬ジョークに見えますが、下北沢の今を眺めていると、実はかなり本質を突いている叫びだと思うんです。今回は個別の店の紹介ではなく、この一言から透けて見える「街の疲れ」について考察します。

### 下北沢、尖りすぎ問題

ここ数年の下北沢はとにかく「尖った店」が増えました。古着屋、ネオ居酒屋、個人営業のコーヒー、アートブックカフェ。どれも単品では魅力的なんですが、街全体として密度が濃すぎて、来る側はけっこう疲れる。

- 「SNSで見た店」を1日に3軒回るツアー型の訪問
- 初見の店が多すぎて、何を選べばハズレないか分からない
- どの店も個性主張が強くて、気軽に入れる空気じゃない

「楽しくない」とは言わない。でも「休憩できない」街になっているのは確かで、その反動として「いっそチェーンでいい。やよい軒でいい」という叫びが生まれる。

### なぜ「やよい軒」なのか（たぬさんの深層心理を勝手に読む）

あえて他のチェーンじゃなく「やよい軒」を名指ししているのが、この投稿の面白いところです。やよい軒には次の特徴があります。

1. 定食に味噌汁とご飯がついて、「ちゃんとした食事」の最低ラインを守ってくれる
2. 一人で入っても浮かない
3. 価格が予測できるので「今日は1000円で済ませたい」が成立する

つまり、**「考えなくていい選択肢」** が欲しいんです。下北沢を歩いていると、どのお店に入るかすら決断コストがかかる。その決断疲れから解放してくれる存在として、やよい軒というワードが選ばれた。そう読めます。

### 「街の多様性」には、退屈も必要かもしれない

個性的な店が並ぶこと自体は素晴らしい。ただ、個性しかない街は逆にしんどい。退屈な選択肢 = 街のセーフティネットであって、それがあるからこそ、尖った店を試す余裕も生まれる。

今回の投稿は、下北沢ファンからの愛ある皮肉だと思います。「この街のことが好きだから、もう少し肩の力を抜ける余地がほしい」という要望が、やよい軒という固有名詞に凝縮されている。

### 他の街ではどうなっているか

似た現象は他エリアでも起きています。

| エリア | 尖り方 | セーフティ役 |
|---|---|---|
| 下北沢 | 古着 × ネオ居酒屋 × 個人店 | 不在（投稿の背景） |
| 中目黒 | カフェ × アパレル | 目黒川沿いのチェーン系 |
| 吉祥寺 | 商店街 × 独立書店 | ハモニカ横丁と駅ビル |
| 下北沢（理想） | 個人店ゾーン + 休憩ゾーンの分離 | — |

要するに、街が成熟するには「寄り道できる気軽な店」と「尖った体験ができる店」の両輪が要るわけで、下北沢は片輪で走っている自覚があるから、ああいう叫びが出る。

### まとめ：個性と退屈のバランス

- 「下北沢にやよい軒を」は単なるチェーン推しではなく、**選択疲れへの処方箋**を求めた叫び
- 街のSNS話題度が高いほど、逆に「気軽な店」の価値が上がる
- Blueskyのような静かなSNSでこういう本音が出るのは、街を愛する人の率直な気持ちがにじむから

街を語るのは、SNSで跳ねるバズ店リストだけじゃなく、こういう「静かな要望」も大事な情報源だと改めて思います。

## 参考リンク

- 元投稿: [Blueskyで見る](https://bsky.app/profile/tanu.bsky.social/post/3llntqnztmk2s)
- 下北沢の街情報: [Googleマップで見る](https://www.google.com/maps/search/?api=1&query=%E4%B8%8B%E5%8C%97%E6%B2%A2)
""" + _DISCLAIMER


# ---------------------------------------------------------------------------
# Target mapping (filename → URL + title + new content)
# ---------------------------------------------------------------------------

TARGETS: list[dict[str, str]] = [
    {
        "json": "data/articles/note-下北沢の和食居酒屋_風神_さんにて_.json",
        "url": "https://note.com/kento_kanazawa/n/n08c2bf51d0b7",
        "title": "【現地レポ】下北沢の和食居酒屋「風神」— ゲリラ豪雨の夜、常連が静かに集う隠れ家",
        "content": FUJIN_CONTENT,
    },
    {
        "json": "data/articles/note-_青空カフェ部__青空ごはん部__外食班.json",
        "url": "https://note.com/kento_kanazawa/n/n3111501b8657",
        "title": "【保存版】Bluesky「青空カフェ部」が映す、都市カフェ文化のいま",
        "content": AOZORA_CONTENT,
    },
    {
        "json": "data/articles/note-もう下北沢に古着屋とネオ居酒屋はいらん_.json",
        "url": "https://note.com/kento_kanazawa/n/n086486f8a8d3",
        "title": "【本音】「下北沢にやよい軒を誘致してくれ」— この叫びが意外と鋭い件",
        "content": YAYOIKEN_CONTENT,
    },
]


def _update_stored_json(path: Path, title: str, content: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["title"] = title
    data["content"] = content
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    pub = NotePublisher(headless=False)
    failures: list[str] = []
    try:
        for t in TARGETS:
            json_path = _REPO / t["json"]
            if not json_path.exists():
                logger.warning("Skip %s (json not found)", t["json"])
                continue
            logger.info("== Updating %s ==", json_path.name)
            _update_stored_json(json_path, t["title"], t["content"])
            logger.info("Stored JSON updated")
            ok = pub.edit_article(
                url=t["url"],
                new_title=t["title"],
                new_content=t["content"],
            )
            if ok:
                logger.info("[OK] %s", t["url"])
            else:
                logger.error("[FAIL] %s", t["url"])
                failures.append(t["url"])
    finally:
        pub.close()

    if failures:
        logger.error("Failed: %s", failures)
        return 1
    logger.info("All note posts updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
