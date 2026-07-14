"""One-shot: fix the 2026-07-15 review findings on 4 live articles
(user decision: paid stay ¥500, fix content/titles).

1. ベビーモニター (¥500): add closing + まとめ (promised最終判定),
   remove unsourced 米国小児科学会 claim, add price disclaimer.
2. 猛暑対策 (¥500): title drops 専門家/氷点下 (both absent from body),
   2025年→2026年 fix.
3. ブロワー (¥0, pre-fix carryover): repair 6 dangling citations,
   complete the truncated final checklist (incident #26 damage).
4. エクソソーム (¥0): kill LLM-fabricated anchor links + fake offers.

Writes fixed content back to local JSON (RAG hygiene).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fix_0715")

_REPO = Path(__file__).resolve().parent.parent
_NOTE_USER = os.environ.get("NOTE_USER", "")
_DANGLING_RE = re.compile(r"（出典:\s*ROOMIE\s*[—ー–-]\s*(?=\n|$)", re.MULTILINE)


def _find(frag: str):
    import glob
    for f in glob.glob(str(_REPO / "data" / "articles" / "*.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        if frag in str(d.get("published_url", "")):
            return Path(f), d
    raise SystemExit(f"article not found: {frag}")


BABYMON_APPEND = """
確認すべきは、①録画データの保存場所（国内か海外か）、②第三者提供の有無、③アカウント削除時のデータ消去ポリシー、の3点です。この3点が明記されていない製品は、機能がどれだけ魅力的でも選択肢から外すのが安全です。

***

## 🏁 まとめ：3分で決める「わが家の最適解」

最後に、ここまでの比較を「どんな家庭に、どれが合うか」という最終判定に落とし込みます。

| わが家のタイプ | 最適解 | 理由 |
| :--- | :--- | :--- |
| **完全ワイヤレス・設置の自由度優先** | Cubo Ai タイプ | 専用アプリ連携と見守り特化設計のバランス |
| **初期費用を抑えて試したい** | VAVA タイプ | モニター一体型でスマホ不要、シンプル運用 |
| **すでにスマートホーム環境がある** | 汎用ネットワークカメラ | 既存エコシステムと統合しやすい |

どのタイプを選ぶ場合でも、本文で述べた「暗号化方式」「データ管理ポリシー」「設置の安全性」の3チェックは必ず購入前に公式サイトで確認してください。

※本文中の価格・仕様は執筆時点の参考情報です。購入前に必ず各メーカー公式サイトで最新情報をご確認ください。
"""

BLOWER_COMPLETION = """1. **安全設計が最優先であること:** 単なる稼働時間だけでなく、「過度な温度上昇を防ぐ自動停止機能」や「充電切れを未然に防ぐ残量表示」のような、道具側がリスクを管理してくれる設計かどうかを最初に確認しましょう。
2. **重量バランスと持ちやすさ:** カタログの重量数値だけでなく、片手で振り回したときの重心バランスが作業の快適さを大きく左右します。可能なら実機を握って確認するのがおすすめです。
3. **騒音レベルと使用シーン:** 集合住宅やベランダで使うなら、パワーより騒音の小ささが実用上の決め手になります。使う時間帯と場所を想定して選びましょう。

この3点をクリアしていれば、小型ブロワーは掃除や作業の頼れる「相棒」になってくれるはずです。"""


def main() -> int:
    from publishers.note_publisher import NotePublisher

    jobs = []

    # --- 1. ベビーモニター ---
    p, d = _find("n8a9dd597b080")
    c = d["content"]
    aap = "また、米国小児科学会が推奨する設置距離に適合している点も重要なポイントです。"
    assert aap in c
    c = c.replace(aap, "また、赤ちゃんから適切な距離を保って設置できる設計かどうかも重要なポイントです。")
    ed, sep, foot = c.partition("<!-- AFFILIATE_SECTION -->")
    ed = ed.rstrip() + "\n" + BABYMON_APPEND.rstrip() + "\n\n"
    c = ed + sep + foot
    jobs.append(("babymon", p, d, "n8a9dd597b080", None, c))

    # --- 2. 猛暑対策 ---
    p, d = _find("n2634246bdb19")
    c = d["content"]
    new_title = "【朗報】猛暑対策の常識が変わる。今日からできる「体感温度を下げる」3ステップ"
    c = c.replace("2025年夏", "2026年夏")
    lines = c.split("\n", 1)
    c = new_title + "\n" + (lines[1] if len(lines) > 1 else "")
    jobs.append(("heat", p, d, "n2634246bdb19", new_title, c))

    # --- 3. ブロワー ---
    p, d = _find("nf5dd50d8f015")
    c = d["content"]
    c, n = _DANGLING_RE.subn("（出典: ROOMIE）", c)
    logger.info("[blower] dangling repaired: %d", n)
    broken = re.search(
        r"1\. \*\*安全設計が最優先であること:\*\*[^\n]*充電切れを未然に防",
        c,
    )
    assert broken, "truncated item not found"
    ed, sep, foot = c.partition("<!-- AFFILIATE_SECTION -->")
    ed = ed[: broken.start()] + BLOWER_COMPLETION + "\n\n"
    c = ed + sep + foot
    jobs.append(("blower", p, d, "nf5dd50d8f015", None, c))

    # --- 4. エクソソーム ---
    p, d = _find("ne61bec069e86")
    c = d["content"]
    kill = [ln for ln in c.split("\n") if "](#" in ln]
    logger.info("[exosome] fake-anchor lines killed: %d", len(kill))
    c = "\n".join(ln for ln in c.split("\n") if "](#" not in ln)
    jobs.append(("exosome", p, d, "ne61bec069e86", None, c))

    pub = NotePublisher()
    failures = 0
    try:
        for key, path, d, note_key, new_title, new_content in jobs:
            lines = new_content.split("\n", 1)
            body = lines[1].lstrip("\n") if len(lines) > 1 else new_content
            url = f"https://note.com/{_NOTE_USER}/n/{note_key}"
            ok = pub.edit_article(url=url, new_title=new_title, new_content=body)
            logger.info("[%s] edit_article: %s", key, ok)
            if not ok:
                failures += 1
                continue
            d["content"] = new_content
            if new_title:
                d["title"] = new_title
            d["fixed_at"] = "2026-07-15"
            d["fix_reason"] = "review CRITICAL: completion/title-claims/dangling/fake-links"
            path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        pub.close()
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
