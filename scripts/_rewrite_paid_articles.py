"""One-shot: rewrite 2 paid notes to be source-faithful, denser, paid-quality.

Background (2026-05-14):
The publish from this morning produced 2 paid notes whose content had
drifted significantly from the actual source story:
  - "5 Years and $5M Later" → article became generic note-writing strategy
  - Cisco Q3 layoffs → article became fabricated "100人に聞いた" Cisco
    product overview, no relation to the actual Q3 earnings news.

User asked for source-strict rewrite + GPT images + denser content
(~7000-9000 chars per article, paid-tier quality).

This script:
1. Loads each article's data/articles/*.json
2. Builds a custom rewrite prompt with verified source facts inline
3. Calls local LLM (Gemma3) to rewrite
4. Saves new content back to the article JSON

Images and note.com edit_article are handled by sibling scripts.
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
logger = logging.getLogger("rewrite_paid")


# --- Verified source facts (from WebFetch / WebSearch 2026-05-14) ---

WASP_FACTS = """
【元記事の検証済みファクト】
- 出典: https://wasp.sh/blog/2026/05/13/new-language-for-web-dev-was-a-mistake
- 著者: Matija Sosic (Co-founder & CEO @ Wasp、双子の兄弟 Martin と共同創業)
- 創業: 2021年 Y Combinator 経由、プレシード $1.5M 調達
- 5年で合計 $5M+ 調達
- 2021年2月 Hacker News で立ち上げ発表
- 2022年9月頃 ベータ移行 + GitHub Stars 1,000 達成
- Wasp は DSL (Domain Specific Language) として始まった。ページ/ルート/API/データモデルを
  「高レベルで宣言」できる言語を目指した
- 結論: 「DSL を作ったこと自体が Mistake だった」
- 主因 1 (採用障壁): "wasp-lang" の名称が JavaScript 置換と誤解された。試すまでの心理的
  ハードルが高かった
- 主因 2 (技術的コスト): VS Code 拡張・LanguageServer の構築に投資しても「我々が目指した
  到達点の 80% まで届かなかった」
- 主因 3 (根本的気づき): "Language was never the moat. It's having a high-level
  understanding of your entire app at compile time." — 言語自体は堀ではなかった、本質は
  「コンパイル時にアプリ全体を高水準で把握できる」こと
- 方向転換: TypeScript SDK を試験導入したところ、新規ユーザーが DSL をスキップして直接
  採用し始めた。これが効いたので、戦略を pivot
- AI 時代との接続: "Wasp fits perfectly here, since it spans the full stack of your
  app and ensures everything works together at all times." — AI 生成コード時代に、
  「全層をカバーする構造化された仕様」は価値を持つと再評価
- 競合参照: RedwoodJS / BlitzJS、構造の参考: Rails / Django / Laravel
"""


CISCO_FACTS = """
【元記事の検証済みファクト】
- 出典: https://www.cnbc.com/2026/05/13/cisco-csco-q3-earnings-report-2026.html
       https://www.foxbusiness.com/technology/cisco-cut-thousands-jobs-ai-push-accelerates-earnings-beat
       https://www.stocktitan.net/sec-filings/CSCO/8-k-cisco-systems-inc-reports-material-event-80905d356577.html
- 発表日: 2026年5月13日 (Q3 FY2026 決算、四半期は4月25日締め)
- 株価: 時間外で +17%
- Q3 売上: $15.84B (アナリスト予想 $15.56B、前年同期 $14.15B から +12% YoY)
- Q3 EPS (調整後): $1.06 (アナリスト予想 $1.04)
- AI インフラ受注: YTD $5.3B、FY2026 通年ガイダンスを「AI 受注 $9B / AI 売上 $4B」に
  引き上げ
- 解雇: 4,000人未満 (全従業員の約5%)、開始日 5月14日
- 解雇に伴う特別費用: 税引前で最大 $1B、うち約 $450M を Q4 FY2026 に計上
- 解雇の理由: AI シフトを加速するための戦略的再配置
- AI 関連製品: ハイパースケーラー向けの AI ネットワーキング (具体的な製品名はソースに
  明記なし。Silicon One / Nexus / Hypershield 等は推測扱いで本文に書かない)
"""


WASP_TITLE = "【完全暴露】Wasp 創業者が $5M と5年を溶かして気づいた「DSL を作るのは堀じゃなかった」— Y Combinator 出身チームの正直すぎる反省録"

CISCO_TITLE = "【速報・完全分析】Cisco 株価+17% と4000人解雇が同日に起きた「2026年5月13日」— AI 受注 $5.3B が示す通信機器メーカーの再定義"


REWRITE_PROMPT_TEMPLATE = """あなたは note.com で月数十万円を稼ぐプロのテックブロガーです。
読者が ¥1,980 払って読みたくなる、濃く、読みやすく、納得感のある有料記事を書いてください。

【厳守ルール — 違反は記事の価値ゼロ】

1. **ソースに厳密アライン**: 下の「検証済みファクト」に書かれていることのみを事実として記述。
   それ以外の数字・人物発言・組織コメントを「事実」として書くのは絶対禁止。
   筆者の見解・分析は「筆者は〜と考える」「個人的には〜と感じる」と明示すれば書いて OK。

2. **架空調査・架空引用 禁止**: 「100人に聞いた」「専門家によれば」「業界関係者は」
   「〇〇大学の研究者が」のような肩書きベースの架空引用は 1 件でも書いたら全文不採用。

3. **見出しは ## H2 / ### H3 を使う**: `**1. heading**` のような太字代用は不可。

4. **総文字数 7,500-9,000 字**: 浅い記事はタイトル負け。本文は密度を持って書く。

5. **構造**:
   - H1 (#) は不要 (タイトルは別途付与される)
   - H2 を最低 6 個 (## 1. / ## 2. / ... 形式 OK)
   - 各 H2 セクション内に H3 1-2 個、または箇条書き、または比較テーブル
   - **比較テーブル (Markdown |---|---| 形式) を最低 2 個** 配置すること
   - 1 セクションあたり 800-1,500 字

6. **トーン**:
   - 「です・ます」+ カジュアル崩し (〜ですよね / 〜じゃないですか / マジで / 正直)
   - 顔文字 (^^) / (´・ω・`) / (TдT) を 2-4 個
   - 絵文字 (🚀 等) は禁止
   - 一人称 (私は / 筆者は) で書き出す

7. **タイトル回収**: タイトルにある数字 ($5M / 5年 / +17% / 4000人 / $5.3B 等) は必ず
   本文で同じ数字を提示し、何を意味するかを解説する。

8. **「筆者の見解」セクション必須**: 客観事実だけでなく、筆者の独自の analysis / takeaway を
   独立した H2 として 1,000 字以上書く。読者が「この筆者の視点で読んでよかった」と思う
   情報を提供する。

9. **末尾**: 参考リンクは元ソース URL のみ。架空 URL は書かない。

---

【記事タイトル (この見出しは記事先頭に H2 で書かない。システムが別途タイトル化する)】
{title}

【検証済みファクト】
{facts}

---

【出力】
記事本文を Markdown で出力してください。最初の行から H2 (`## `) で始めて、最後まで本文の
みを出力してください。タイトル行・前置き・後書きの説明文 (「以下、記事です：」等) は
不要です。
"""


def rewrite_article(
    article_id: str, title: str, facts: str, save: bool = True
) -> tuple[str, Path]:
    """Rewrite one article with strict source fidelity.

    Returns (new_content, article_path).
    """
    art_path = _REPO / "data" / "articles" / f"{article_id}.json"
    if not art_path.exists():
        raise FileNotFoundError(art_path)
    art_data = json.loads(art_path.read_text(encoding="utf-8"))

    from generators.llm_config import get_llm
    llm = get_llm("writer")
    if not llm.is_available():
        raise RuntimeError("ローカル LLM が利用不可。Ollama serve を確認")

    prompt = REWRITE_PROMPT_TEMPLATE.format(title=title, facts=facts)
    logger.info("rewriting %s (prompt_len=%d)", article_id, len(prompt))
    out = llm.generate(prompt, temperature=0.75)
    if not out or len(out.strip()) < 1500:
        raise RuntimeError(
            f"LLM output too short ({len(out)} chars). aborting."
        )

    # Strip any leading explanation lines
    lines = out.splitlines()
    while lines and not lines[0].startswith("##"):
        lines.pop(0)
    out = "\n".join(lines).strip()

    # Apply the existing structural post-processor for safety
    bold_re = re.compile(r"^\*\*(\d+\.\s+[^\n*][^\n]*?)\*\*[ \t]*$", re.MULTILINE)
    out = bold_re.sub(r"## \1", out)

    h2_count = len(re.findall(r"^##\s+\S", out, re.MULTILINE))
    table_count = len(re.findall(r"^\|[\s\-:]+\|", out, re.MULTILINE))
    logger.info(
        "rewrite done — chars=%d h2=%d tables=%d",
        len(out), h2_count, table_count,
    )

    if save:
        # Backup old content first
        art_data["_content_before_rewrite_20260514"] = art_data.get("content", "")
        art_data["title"] = title
        art_data["content"] = out
        art_path.write_text(
            json.dumps(art_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("saved to %s", art_path)
    return out, art_path


JOBS = [
    {
        "article_id": "note-5_Years_and__5M_Late-f1b21453",
        "title": WASP_TITLE,
        "facts": WASP_FACTS,
    },
    {
        "article_id": "note-Cisco_s_stock_pops_1-5224bf4f",
        "title": CISCO_TITLE,
        "facts": CISCO_FACTS,
    },
]


if __name__ == "__main__":
    for j in JOBS:
        try:
            rewrite_article(j["article_id"], j["title"], j["facts"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("FAILED rewrite for %s: %s", j["article_id"], exc)
