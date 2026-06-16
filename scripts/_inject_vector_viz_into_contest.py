"""Update the #AIで遊ぼう contest entry (n444be2daa2ef): insert a new
"おまけ: 「ベクトル」を実際に見てみる" section just before 「なぜ書くか」
with three 3D-RAG visualization screenshots so readers can SEE what a
vector space actually looks like.

Cover stays the existing ChatGPT k-beauty poster. Inline images become
the 3 RAG screenshots so the section's images render correctly.
"""
from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for ln in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("inject_viz")

from publishers.note_publisher import NotePublisher  # noqa: E402

NOTE_URL = "https://note.com/<NOTE_USER>/n/n444be2daa2ef"
BODY_PATH = _REPO / "data" / "custom_posts" / "2026-06-21_ai_de_asobou_body.md"
IMG_DIR = _REPO / "data" / "images" / "contest"
COVER_PATH = (_REPO / "data" / "images" / "covers"
              / "chatgpt_2026_06_21_ai_de_asobou_20260617_000910_535537_23620_cover.png")

NEW_SECTION = """## おまけ:「ベクトル」を実際に見てみる

ここまで「RAG」「embedding」「591 chunks」「768 次元」と何度か書いてきたけれど、言葉だけだと「結局それ、数式の話でしょ」と感じる方も多いと思う。

実はこのシステムが毎日使っている「ベクトル空間」は、視覚的にはこういう見た目をしている。

![RAGベクトル空間の3D俯瞰 591ベクトルが7コレクションに分かれて散らばっている](data/images/contest/rag_3d_overview.png)

これは、私のリポが現時点で持っている **591 個のベクトル**を、もともと **768 次元**だったものを **t-SNE** という手法で 3 次元に圧縮して、散布図にしたもの。一つ一つの点が「過去記事の要約」「ハルシ事故の事例」「サムネのスタイル」などのチャンクで、**似た意味を持つ点ほど互いに近くに配置される**。

色は **コレクション**(このシステム内での意味カテゴリ)を示していて、7 種類ある。

- 🟦 **青(past_articles, 457個)**: 私の過去記事の要約。全体の 8 割を占める巨大群
- 🟢 **緑(generation_guides, 69個)**: 生成ルール文書
- 🟥 **赤(hallucinations, 18個)**: 過去のハルシ事故事例(守り)
- 🟧 **オレンジ(ops_incidents, 16個)**: 運用バグ事例(守り)
- 🟪 **ピンク(thumbnail_styles, 15個)**: サムネのスタイル知識
- 🟩 **濃緑(successes, 8個)**: 上位エンゲ記事のパターン
- 🟨 **黄(anti_patterns, 8個)**: 下位エンゲ記事のパターン

ズームして覗いてみると、こんなものが見えてくる。

![K-beauty クラスタの拡大 過去記事の青と成功パターンの緑が同じ意味空間で隣接](data/images/contest/rag_3d_kbeauty_cluster.png)

これは「**K-beauty 関連**」のチャンクが集まっている領域。過去記事の青と「マネすべき型」の濃緑が、まさに**意味空間として隣り合って**いる。これが「K-beauty を書くなら過去の K-beauty 記事の型を参照する」という挙動を、数式ではなく**空間的な近さ**として実現している正体です。

逆に、別の角度から見ると守り系のかたまりが見える。

![防御系コレクション hallucinations と ops_incidents は独立した島を作る](data/images/contest/rag_3d_defenders_island.png)

ハルシ事故(赤)と運用事故(オレンジ)は、通常記事の領域から離れて**独立した島**を形成している。これが、「新しい記事を書くときに、過去のハルシパターン群と意味的に近い場合にだけ警告を出す」防御を可能にしている。**危ない言葉遣いに意味で似ているだけで、過去事故の島から「あなたの記事、こっちの島に近いですよ」と引っ張られる**、と思ってもらえばいい。

「AI に学習させる」って、教科書に書いてある重みベクトルとかの話だけじゃなくて、結局これくらい**絵的に見える**ものなんだなあ、とこの図を初めて自分で描いた時に思った。嬉しかった。

ちなみにこの図は、私のリポにある `scripts/visualize_rag_graph.py` というスクリプトを叩くと、自分のローカルで HTML として書き出される。ドラッグでぐりぐり回したり、ホバーすると一つ一つの点が何のチャンクなのかが読める。**自分で動かせる地図**として、私の朝のチェックリストに入っている道具のひとつ。

---
"""


def main() -> int:
    body = BODY_PATH.read_text(encoding="utf-8")

    # Locate the 「なぜ書くか」 H2 and inject our new section right before it.
    marker = "## なぜ書くか"
    if marker not in body:
        log.error("marker '%s' not found in body — abort", marker)
        return 1
    new_body = body.replace(marker, NEW_SECTION + "\n" + marker, 1)
    log.info("body grew %d -> %d chars", len(body), len(new_body))

    # The three RAG screenshots become the new inline image set; the
    # existing ChatGPT cover stays as the cover.
    inline_paths = [
        str((IMG_DIR / "rag_3d_overview.png").resolve()),
        str((IMG_DIR / "rag_3d_kbeauty_cluster.png").resolve()),
        str((IMG_DIR / "rag_3d_defenders_island.png").resolve()),
    ]
    for p in inline_paths:
        if not Path(p).exists():
            log.error("missing image: %s", p)
            return 2
    log.info("inline images: %d", len(inline_paths))
    log.info("cover stays: %s", COVER_PATH.name)

    pub = NotePublisher(headless=False)
    try:
        ok = pub.edit_article(
            url=NOTE_URL,
            new_content=new_body,
            inline_image_paths=inline_paths,
            cover_image_path=str(COVER_PATH.resolve()),
        )
        log.info("edit_article returned: %s", ok)
        return 0 if ok else 3
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
