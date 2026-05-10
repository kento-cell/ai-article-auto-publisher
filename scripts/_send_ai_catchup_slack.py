"""Send the GW (Golden Week) AI catch-up summary to Slack.

Posts a Codex + Claude rundown for 2026-04-20..05-07 to the
configured Slack webhook. Uses Block Kit so the message stays
readable on mobile.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import requests  # noqa: E402

WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")
if not WEBHOOK:
    print("NO_WEBHOOK_CONFIGURED")
    sys.exit(2)

HEADER = (
    ":robot_face: *GW明け AIキャッチアップ — Codex × Claude (2026-04-20〜05-07)*\n"
    "_自動収集・一次ソース優先。リンクは公式 / 信頼テック媒体のみ_"
)

CODEX = """*:openai: OpenAI Codex*

*1. Codex 大型アップデート (4/16) — 「ほぼ何でもできる」相棒へ*
• *Computer Use 解禁*: Codex がカーソル操作。複数エージェント並列実行も本人作業を邪魔しない設計 <https://openai.com/index/codex-for-almost-everything/|Source>
• *In-app ブラウザ + 画像生成 (gpt-image-1.5)*: ブラウザに直接コメントで指示、フロント・モック・ゲーム画像を同一ワークフロー内で生成
• *Memory プレビュー*: 個人の好み・修正指示・知見をセッション横断で記憶
• *スケジューリング*: 数日〜数週間の長期タスクを Codex 自身が予約・継続
• *90+ プラグイン拡充*: Atlassian Rovo / CircleCI / CodeRabbit / GitLab Issues / Microsoft Suite / Neon / Render

*2. Codex CLI: Windows ネイティブ + 新モデル*
• *Windows ネイティブ サンドボックス*: WSL不要、PowerShell + OS firewall でプロキシのみ通すバイパス不能設計 <https://daily1bite.com/en/blog/ai-tools/openai-codex-cli-april-2026-update|Source>
• *GPT-5.3-Codex-Spark (preview)*: 1000+ TPS のリアルタイム コーディングモデル、CLI/IDE/Codexアプリ同梱 (Pro限定) <https://openai.com/index/introducing-gpt-5-3-codex-spark/|Source>
• *GPT-5.5 / 5.5 Pro が API 公開 (4/24)*: 5.4より高知能 + トークン効率改善 <https://techcrunch.com/2026/04/23/openai-chatgpt-gpt-5-5-ai-model-superapp/|Source>

*3. 料金・レート関連*
• *4/2 課金体系刷新*: メッセージ数 → API トークン換算へ統一 (全プラン) <https://www.getaiperks.com/en/articles/codex-pricing|Source>
• *4/28 全有料プランでレート上限リセット*。Pro $200 は 5/31 まで25x Plus優遇継続 <https://community.openai.com/t/codex-rate-limits-reset-for-all-paid-plans-april-28-2026/1379921|Source>"""

CLAUDE_SECTION = """*:anthropic: Anthropic Claude*

*1. Claude Opus 4.7 GA (4/16) — コーディング & 長文の本命*
• *1M コンテキストが標準価格で開放* ($5/$25 per 1M tokens、4.6と同額) — 長文プレミアム廃止 <https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7|Source>
• *高解像度Vision*: 2576px / 3.75MP まで対応 (Claude史上初) <https://www.anthropic.com/news/claude-opus-4-7|Source>
• *⚠ 罠*: 新トークナイザーで同文章のトークン数が最大35%増 — 表示価格据え置きでも実質コストは上振れ可能性 <https://www.finout.io/blog/claude-opus-4.7-pricing-the-real-cost-story-behind-the-unchanged-price-tag|Source>

*2. Claude Code (CLI) アップデート*
• `/skills` *検索ボックス追加* — type-to-filter で即着地 <https://releasebot.io/updates/anthropic/claude-code|Source>
• *Hooks 強化*: PostToolUse が MCP 以外でも `updatedToolOutput` でツール出力書き換え可、`duration_ms` も追加
• `claude plugin prune` *新設* — 孤立した依存プラグインを掃除
• *Q1で出揃った機能*: Remote Control / Dispatch / Auto Mode (`--dangerously-skip-permissions` の安全代替) <https://www.mindstudio.ai/blog/claude-code-q1-2026-update-roundup|Source>

*3. Claude API / Agent SDK*
• *Memory for Managed Agents (public beta)*: ヘッダ `managed-agents-2026-04-01` でセッション横断学習 <https://releasebot.io/updates/anthropic|Source>
• *Prompt caching が自動化*: `cache_control` 1か所で末尾ブロック自動キャッシュ — 手動ブレークポイント管理不要 <https://platform.claude.com/docs/en/build-with-claude/prompt-caching|Source>
• *2/5以降 cache はワークスペース単位で隔離*
• *Claude Design (Anthropic Labs)*: プロトタイプ / スライド / 1ページャー共作
• *Microsoft 365 add-in 公開 (5月)*: Excel / PowerPoint / Word で Claude 動作"""

ACTIONS = """*:dart: 個人開発者として今週試すべき TOP 3*

1. *Codex CLI を最新版へ + Windows ネイティブ サンドボックス検証*
   既知の Codex ハング (本リポで踏んだ事例あり) が WSL 依存を外して改善するか実測する価値あり。Spark プレビューも合わせて触る <https://daily1bite.com/en/blog/ai-tools/openai-codex-cli-april-2026-update|Source>

2. *Claude API の自動 prompt caching へ移行*
   `cache_control` 1個追加で済む新仕様。記事生成パイプラインの構成パターン・理念・評価ルーブリックをキャッシュ化すれば実効コスト大幅減 <https://platform.claude.com/docs/en/build-with-claude/prompt-caching|Source>

3. *Opus 4.7 の高解像度 Vision を eyecatch QA に投入*
   `scripts/probe_eyecatch_ui.py` + 画像ハルシネーション3層ゲートと組み合わせて 2576px 入力で再評価。チェーン店判定 / 禁止記号検出の精度向上が見込める <https://www.anthropic.com/news/claude-opus-4-7|Source>

_本リポへの導入差分は別途PR化推奨_"""


def chunked(text: str, limit: int = 2900) -> list[str]:
    """Split text into <limit chars chunks on paragraph boundaries."""
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    cur = ""
    for p in paragraphs:
        if len(cur) + len(p) + 2 > limit and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def post(text: str) -> int:
    r = requests.post(
        WEBHOOK,
        data=json.dumps({"text": text, "mrkdwn": True}),
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    return r.status_code


parts = [HEADER, CODEX, CLAUDE_SECTION, ACTIONS]
fail = 0
for i, body in enumerate(parts, 1):
    for chunk in chunked(body):
        code = post(chunk)
        print(f"part {i}: status={code}")
        if code != 200:
            fail += 1

sys.exit(0 if fail == 0 else 1)
