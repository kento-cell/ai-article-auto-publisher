"""Second pass: expand the source-aligned rewrites to paid-tier density.

Background (2026-05-14): the first rewrite pass produced source-faithful
content but only 3500-4800 chars per article. The user requested
paid-tier density (~7500-9000 chars). This script takes the current
article content and runs a "deepen each section + add 2 new H2s" pass.

Strict source fidelity preserved by passing the canonical verified
facts inline (same as rewrite pass).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_ENV = _REPO / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("expand_paid")


from scripts._rewrite_paid_articles import (  # noqa: E402
    WASP_FACTS, CISCO_FACTS,
)


EXPAND_PROMPT = """以下は、検証済みファクトに基づいて書かれた note 有料記事の現行ドラフトです。
内容は良いのですが、有料記事 (¥1,980) としては分量と濃度がまだ不足しています。
今のドラフトを **濃化編集** してください。

【守ること — 違反禁止】

1. **ソースに厳密アライン**: 下の「検証済みファクト」に書かれていることのみが事実。
   ファクト以外の数字・人物発言・組織コメントを「事実」として書くのは絶対禁止。
   推測・分析は「筆者の見解では」「個人的には」と明示すれば書いて OK。

2. **架空調査・架空引用 絶対禁止**: 「100人に聞いた」「専門家によれば」「業界関係者は」
   「〇〇大学の研究者が」のような肩書きベースの架空引用は不可。

3. **既存の H2 構造を保ちつつ、各 H2 セクションを 1,200-1,800 字に拡張**。
   薄いセクションを膨らませる。具体例・仮説・読者への問いかけを追加。
   ただし新しい固有名詞・数字はファクトから引っぱってきたものだけ。

4. **以下の追加 H2 セクションを新規で 2-3 個 加える** (各 1,200-1,500 字):
   - 「## 同じ轍を踏まないための X つのチェックリスト」 (筆者の見解として)
   - 「## 読者の質問に答える Q&A」 (3-5 個の Q&A)
   - 「## この事例から見えてくる N年後の業界」 (筆者の予測として明示)
   どれを選ぶかは記事に合わせて。

5. **総文字数 目標 8,000-10,000 字**。

6. **比較テーブル を最低 3 個** (Markdown |---|---| 形式)。

7. **見出しは ## H2 / ### H3 を使う**。`**1. heading**` 太字代用は禁止。

8. **トーン保持**: 既存ドラフトのカジュアル「です・ます」+ 顔文字 (^^) (´・ω・`) を保ちつつ、
   筆者の見解パートでは「正直」「ぶっちゃけ」「マジで」を適度に。絵文字 (🚀 等) は禁止。

9. **末尾の「参考リンク」セクションは既存のまま残す**。新しい URL を捏造しない。

【検証済みファクト (これ以外は事実として書かない)】
{facts}

---

【現行ドラフト】
{current}

---

【出力】
濃化編集後の記事本文 Markdown のみを出力してください。前置きや「以下、編集版です：」
のような説明文は不要。最初の行から H2 (`## `) で始めてください。
"""


JOBS = [
    {
        "article_id": "note-5_Years_and__5M_Late-f1b21453",
        "facts": WASP_FACTS,
    },
    {
        "article_id": "note-Cisco_s_stock_pops_1-5224bf4f",
        "facts": CISCO_FACTS,
    },
]


def expand_one(article_id: str, facts: str) -> None:
    art_path = _REPO / "data" / "articles" / f"{article_id}.json"
    d = json.loads(art_path.read_text(encoding="utf-8"))
    current = d["content"]
    before = len(current)
    logger.info("expanding %s (current=%d chars)", article_id, before)

    from generators.llm_config import get_llm
    llm = get_llm("writer")
    if not llm.is_available():
        raise RuntimeError("ローカル LLM が利用不可")

    prompt = EXPAND_PROMPT.format(facts=facts, current=current)
    out = llm.generate(prompt, temperature=0.7)
    if not out or len(out.strip()) < before:
        logger.warning(
            "expand produced shorter output (%d < %d) — keeping existing",
            len(out or ""), before,
        )
        return

    lines = out.splitlines()
    while lines and not lines[0].startswith("##"):
        lines.pop(0)
    out = "\n".join(lines).strip()

    # Apply structural post-processor
    bold_re = re.compile(r"^\*\*(\d+\.\s+[^\n*][^\n]*?)\*\*[ \t]*$", re.MULTILINE)
    out = bold_re.sub(r"## \1", out)

    h2 = len(re.findall(r"^##\s+\S", out, re.MULTILINE))
    tab = len(re.findall(r"^\|[\s\-:]+\|", out, re.MULTILINE))
    logger.info(
        "expand done — before=%d after=%d h2=%d tables=%d",
        before, len(out), h2, tab,
    )

    d["_content_before_expand_20260514"] = current
    d["content"] = out
    art_path.write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("saved to %s", art_path)


if __name__ == "__main__":
    for j in JOBS:
        try:
            expand_one(j["article_id"], j["facts"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("FAILED expand for %s: %s", j["article_id"], exc)
