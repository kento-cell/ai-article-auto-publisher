"""Multi-agent article regeneration pipeline.

When a user marks an article as "🔄再生成" in Google Sheets, this module
orchestrates a 5-agent discussion (Researcher -> Strategist -> Writer ->
Critic -> Coordinator) to produce a richer, higher-quality version.

Each agent is simulated as a separate prompt to the local LLM (Gemma3 via Ollama).
The discussion log is preserved for debugging and Slack reporting.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from generators.local_llm import LocalLLM

logger = logging.getLogger(__name__)

# Max Writer<->Critic revision rounds
MAX_REVISION_ROUNDS = 2

# Directory for agent discussion logs
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "regeneration"


class Regenerator:
    """Orchestrate multi-agent regeneration pipeline.

    Each agent call is a single llm.generate(prompt) call.
    Prompts are in Japanese to match article output language.
    """

    def __init__(self, llm: LocalLLM) -> None:
        self.llm = llm
        self._discussion_log: list[dict[str, str]] = []

    def regenerate(
        self,
        original_article: dict,
        additional_context: str = "",
    ) -> dict:
        """Run multi-agent regeneration pipeline.

        Args:
            original_article: Dict with title, content, platform, source,
                rejection_reasons (from ArticleStore).
            additional_context: Any extra context from user.

        Returns:
            Dict with:
                - title: str
                - content: str (regenerated article)
                - platform: str
                - agent_discussion: list of {agent, content} dicts
                - regenerated_at: ISO timestamp
                - error: str or None
        """
        self._discussion_log = []
        title = original_article.get("title", "untitled")
        platform = original_article.get("platform", "")
        source_content = ""
        source = original_article.get("source", {})
        if isinstance(source, dict):
            source_content = source.get("content", "")
        elif isinstance(source, str):
            source_content = source
        rejection_reasons = original_article.get(
            "rejection_reasons",
            original_article.get("scores", {}).get("summary", ""),
        )
        original_content = original_article.get("content", "")

        logger.info(
            "Regeneration started: %s [%s]", title[:40], platform,
        )

        result = {
            "title": title,
            "content": "",
            "platform": platform,
            "agent_discussion": [],
            "regenerated_at": datetime.now().isoformat(),
            "error": None,
        }

        try:
            # Phase 1: Researcher
            research_brief = self._run_researcher(
                title, source_content, rejection_reasons, additional_context,
            )

            # Phase 2: Strategist
            strategy_brief = self._run_strategist(
                title, research_brief, platform,
            )

            # Phase 3: Writer (initial draft)
            draft = self._run_writer(
                title, research_brief, strategy_brief, platform,
            )

            # Phase 4-5: Critic review + Writer revision loop
            final_draft = self._run_critique_loop(
                draft, research_brief, strategy_brief, platform,
            )

            # Phase 6: Coordinator final judgment
            coordinator_result = self._run_coordinator(
                title, final_draft, research_brief,
            )

            result["content"] = final_draft
            result["title"] = self._extract_title(final_draft) or title
            result["coordinator_judgment"] = coordinator_result
            result["agent_discussion"] = list(self._discussion_log)

        except (ConnectionError, RuntimeError) as e:
            logger.error("Regeneration LLM error for '%s': %s", title[:30], e)
            result["error"] = str(e)
            result["agent_discussion"] = list(self._discussion_log)
        except Exception as e:
            logger.error(
                "Regeneration unexpected error for '%s': %s", title[:30], e,
            )
            result["error"] = str(e)
            result["agent_discussion"] = list(self._discussion_log)

        # Save discussion log to file
        self._save_discussion_log(title, platform)

        return result

    # ------------------------------------------------------------------
    # Agent phases
    # ------------------------------------------------------------------

    def _run_researcher(
        self,
        title: str,
        source_content: str,
        rejection_reasons: str,
        additional_context: str,
    ) -> str:
        """Phase 1: Researcher investigates the topic."""
        prompt = (
            "あなたはリサーチャーです。以下のトピックについて深掘り調査を行ってください。\n\n"
            f"【トピック】\n{title}\n\n"
            f"【元記事の内容（抜粋）】\n{source_content[:2000]}\n\n"
            f"【前回の不合格理由】\n{rejection_reasons}\n\n"
        )
        if additional_context:
            prompt += f"【追加コンテキスト】\n{additional_context}\n\n"

        prompt += (
            "【タスク】\n"
            "1. このトピックに関する追加の視点・情報を特定する\n"
            "2. 関連する専門家の意見、反論、データポイントを収集する\n"
            "3. 前回の不合格理由を踏まえ、どのような情報が不足していたかを分析する\n"
            "4. ソースの信用度を評価する（Tier1: 学術論文・公式, Tier2: 大手メディア, "
            "Tier3: コミュニティ, Tier4: 未検証）\n\n"
            "【出力形式】\n"
            "以下の構造化されたリサーチブリーフを作成してください:\n"
            "- 検証済み事実（ソースと信用度ティア付き）\n"
            "- 未検証の主張（なぜ検証できなかったか）\n"
            "- 反論・制限事項\n"
            "- 推奨する記事改善方向\n"
        )

        logger.info("[Researcher] Generating research brief...")
        response = self.llm.generate(prompt, temperature=0.5)
        self._log_agent("Researcher", response)
        return response

    def _run_strategist(
        self,
        title: str,
        research_brief: str,
        platform: str,
    ) -> str:
        """Phase 2: Strategist proposes differentiation angle."""
        platform_note = ""
        if platform == "zenn":
            platform_note = (
                "ターゲット: 日本のWebエンジニア。技術的深さと実践性を重視。"
            )
        elif platform == "note":
            platform_note = (
                "ターゲット: 一般読者。読みやすさ、共感性、バズりやすさを重視。"
            )

        prompt = (
            "あなたはストラテジストです。以下のリサーチブリーフに基づいて、"
            "記事の差別化戦略を立案してください。\n\n"
            f"【トピック】\n{title}\n\n"
            f"【リサーチブリーフ】\n{research_brief[:3000]}\n\n"
            f"【プラットフォーム】\n{platform} — {platform_note}\n\n"
            "【タスク】\n"
            "1. 既存記事との差別化角度を提案する（なぜこの角度が有効か理由付き）\n"
            "2. 記事の構成（見出し案）を提案する\n"
            "3. ターゲット読者が「この記事でしか得られない」と感じるポイントを明確にする\n"
            "4. 記事のトーン・スタイルの方向性を指示する\n\n"
            "【出力形式】\n"
            "- 差別化角度（1-2文で明確に）\n"
            "- 記事構成案（見出しリスト）\n"
            "- キーメッセージ（読者へのコア価値）\n"
            "- トーン指示\n"
        )

        logger.info("[Strategist] Generating strategy brief...")
        response = self.llm.generate(prompt, temperature=0.7)
        self._log_agent("Strategist", response)
        return response

    def _run_writer(
        self,
        title: str,
        research_brief: str,
        strategy_brief: str,
        platform: str,
    ) -> str:
        """Phase 3: Writer drafts the full article."""
        style_rules = (
            "【執筆スタイル -- 最重要ルール】\n"
            "- 元記事の要約・翻訳・書き直しは絶対禁止。独自の分析と見解を中心に\n"
            "- 複数ソースの意見・データ・専門家の見解を統合する\n"
            "- 賛否が分かれるテーマでは明確にポジションを取る（中立禁止）\n"
            "- 最終的に「筆者はこう考える」と自分の言葉で結論を出す\n"
            "- 事実の引用は出典付きで短く。分析・解釈・示唆が記事の主体\n"
        )

        citation_rules = (
            "【引用ルール】\n"
            "引用は必ず以下の形式で:\n"
            '> "引用文"\n'
            ">\n"
            '> 出典: 著者/組織名. "タイトル"\n'
            "> URL\n"
            "> (取得日: YYYY年MM月DD日)\n"
        )

        checklist = (
            "【必須チェックリスト】\n"
            "- H2見出し(##)を最低4個\n"
            "- H1(#)はタイトルのみ\n"
            "- 引用ブロック(>)を最低3箇所、各引用に出典URL+取得日\n"
            "- Mermaid図またはテーブルを最低1個\n"
            "- 参考文献セクション(## 参考文献)を末尾に配置\n"
            "- 文字数: 2500-3500字（コード除く）\n"
        )

        prompt = (
            "あなたはライターです。以下のリサーチブリーフと戦略ブリーフに基づいて、"
            "完全なオリジナル記事を執筆してください。\n\n"
            f"【トピック】\n{title}\n\n"
            f"【リサーチブリーフ】\n{research_brief[:3000]}\n\n"
            f"【戦略ブリーフ】\n{strategy_brief[:2000]}\n\n"
            f"{style_rules}\n"
            f"{citation_rules}\n"
            f"{checklist}\n"
            "Markdown形式で完全な記事を出力してください。\n"
        )

        logger.info("[Writer] Generating initial draft...")
        response = self.llm.generate(prompt, temperature=0.7)
        self._log_agent("Writer", response)
        return response

    def _run_critic(
        self,
        draft: str,
        research_brief: str,
        strategy_brief: str,
    ) -> str:
        """Phase 4: Critic reviews the draft from a position of denial."""
        prompt = (
            "あなたは批評家です。常に否定から入ります。肯定は仕事ではありません。\n"
            "以下の記事ドラフトを厳しくレビューしてください。\n\n"
            f"【記事ドラフト】\n{draft[:4000]}\n\n"
            f"【リサーチブリーフ（照合用）】\n{research_brief[:2000]}\n\n"
            f"【戦略ブリーフ（照合用）】\n{strategy_brief[:1000]}\n\n"
            "【レビュー観点】\n"
            "1. 独自性: 元記事の焼き直しではないか？差別化角度は有効か？\n"
            "2. 正確性: リサーチブリーフと矛盾していないか？未検証主張を断定していないか？\n"
            "3. 可読性: 構成は論理的か？見出しで全体像が掴めるか？\n"
            "4. 引き込み: 読者は最後まで読むか？冒頭は引き込めるか？結論はアクショナブルか？\n"
            "5. 引用・出典: 十分な数か？形式は正しいか？Tier1-2ソースが核心に使われているか？\n"
            "6. 視覚要素: 図表・Mermaid・テーブルは十分か？\n\n"
            "【出力形式】\n"
            "各観点について具体的な問題点を指摘してください。\n"
            "問題がない観点は「指摘すべき点がない」と明記。\n"
            "曖昧な指摘はしないこと。「セクションXのY主張は〜」のように具体的に。\n"
            "最後に、総合判定を記載: APPROVE（指摘なし）/ REVISE（修正必要）/ REJECT（根本的問題）\n"
        )

        logger.info("[Critic] Reviewing draft...")
        response = self.llm.generate(prompt, temperature=0.3)
        self._log_agent("Critic", response)
        return response

    def _run_writer_revision(
        self,
        draft: str,
        critic_feedback: str,
        research_brief: str,
        round_num: int,
    ) -> str:
        """Phase 5: Writer revises based on Critic feedback."""
        prompt = (
            f"あなたはライターです。批評家からのフィードバック（修正ラウンド{round_num}）に基づいて、"
            "記事を改訂してください。\n\n"
            f"【現在のドラフト】\n{draft[:4000]}\n\n"
            f"【批評家のフィードバック】\n{critic_feedback[:2000]}\n\n"
            f"【リサーチブリーフ（参照用）】\n{research_brief[:2000]}\n\n"
            "【指示】\n"
            "- 批評家が指摘した具体的な問題点を全て修正する\n"
            "- 修正によって既存の良い部分を壊さない\n"
            "- 引用・出典の不足があれば追加する\n"
            "- 視覚要素の不足があれば追加する\n"
            "- 改訂した完全な記事をMarkdown形式で出力する\n"
        )

        logger.info("[Writer] Revision round %d...", round_num)
        response = self.llm.generate(prompt, temperature=0.7)
        self._log_agent(f"Writer (revision {round_num})", response)
        return response

    def _run_critique_loop(
        self,
        draft: str,
        research_brief: str,
        strategy_brief: str,
        platform: str,
    ) -> str:
        """Run Writer<->Critic loop (max MAX_REVISION_ROUNDS)."""
        current_draft = draft

        for round_num in range(1, MAX_REVISION_ROUNDS + 1):
            critic_feedback = self._run_critic(
                current_draft, research_brief, strategy_brief,
            )

            # Check if Critic approved
            feedback_lower = critic_feedback.lower()
            if "approve" in feedback_lower and "revise" not in feedback_lower:
                logger.info(
                    "[Critic] Approved at round %d", round_num,
                )
                break

            if "reject" in feedback_lower:
                logger.warning(
                    "[Critic] Rejected at round %d. Attempting revision anyway.",
                    round_num,
                )

            # Writer revises
            current_draft = self._run_writer_revision(
                current_draft, critic_feedback, research_brief, round_num,
            )

        return current_draft

    def _run_coordinator(
        self,
        title: str,
        final_draft: str,
        research_brief: str,
    ) -> dict:
        """Phase 6: Coordinator collects discussion and makes final judgment."""
        discussion_summary = "\n\n".join(
            f"[{entry['agent']}]\n{entry['content'][:500]}"
            for entry in self._discussion_log
        )

        prompt = (
            "あなたはコーディネーターです。以下のマルチエージェントディスカッションの結果を評価し、"
            "最終判定を行ってください。\n\n"
            f"【トピック】\n{title}\n\n"
            f"【ディスカッション概要】\n{discussion_summary[:4000]}\n\n"
            f"【最終ドラフト冒頭】\n{final_draft[:2000]}\n\n"
            "【タスク】\n"
            "以下のJSON形式で最終判定を出力してください:\n"
            "```json\n"
            "{\n"
            '  "judgment": "PASS または FAIL",\n'
            '  "quality_assessment": "品質の総合評価（1-2文）",\n'
            '  "remaining_issues": ["未解消の問題があれば列挙"],\n'
            '  "recommendation": "承認推奨 / 条件付き承認 / 再検討推奨"\n'
            "}\n"
            "```\n"
        )

        logger.info("[Coordinator] Final judgment...")
        response = self.llm.generate(prompt, temperature=0.3)
        self._log_agent("Coordinator", response)

        # Try to parse JSON from coordinator response
        return self._parse_coordinator_response(response)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log_agent(self, agent: str, content: str) -> None:
        """Record an agent's contribution to the discussion log."""
        self._discussion_log.append({
            "agent": agent,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        logger.info(
            "[%s] Response: %d chars", agent, len(content),
        )

    def _save_discussion_log(self, title: str, platform: str) -> None:
        """Save the full discussion log to a file for debugging."""
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title[:30])
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{platform}_{safe_title}.md"
            path = LOG_DIR / filename

            lines = [
                f"# Regeneration Discussion Log",
                f"",
                f"- **Title**: {title}",
                f"- **Platform**: {platform}",
                f"- **Timestamp**: {datetime.now().isoformat()}",
                f"- **Agents**: {len(self._discussion_log)} entries",
                f"",
                f"---",
                f"",
            ]
            for entry in self._discussion_log:
                lines.append(f"## {entry['agent']}")
                lines.append(f"*{entry['timestamp']}*")
                lines.append(f"")
                lines.append(entry["content"])
                lines.append(f"")
                lines.append(f"---")
                lines.append(f"")

            path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Discussion log saved: %s", path)
        except Exception as e:
            logger.error("Failed to save discussion log: %s", e)

    @staticmethod
    def _extract_title(article: str) -> Optional[str]:
        """Extract H1 title from markdown article."""
        match = re.search(r"^#\s+(.+)$", article, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _parse_coordinator_response(response: str) -> dict:
        """Parse Coordinator's JSON judgment from response text."""
        # Try to find JSON block
        json_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL,
        )
        json_str = None
        if json_match:
            json_str = json_match.group(1)
        else:
            start = response.find("{")
            if start != -1:
                depth = 0
                for i, ch in enumerate(response[start:], start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            json_str = response[start:i + 1]
                            break

        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # Fallback: heuristic judgment from text
        lower = response.lower()
        if "pass" in lower and "fail" not in lower:
            judgment = "PASS"
        elif "fail" in lower:
            judgment = "FAIL"
        else:
            judgment = "UNCERTAIN"

        return {
            "judgment": judgment,
            "quality_assessment": response[:200],
            "remaining_issues": [],
            "recommendation": "再検討推奨",
        }

    def get_discussion_summary(self, max_length: int = 2000) -> str:
        """Get a formatted summary of the agent discussion for Slack.

        Args:
            max_length: Max total character length.

        Returns:
            Formatted discussion summary string.
        """
        if not self._discussion_log:
            return "(no discussion recorded)"

        lines = []
        for entry in self._discussion_log:
            agent = entry["agent"]
            content = entry["content"]
            # Truncate each agent's content
            per_agent_max = max_length // max(len(self._discussion_log), 1)
            truncated = content[:per_agent_max]
            if len(content) > per_agent_max:
                truncated += "..."
            lines.append(f"*[{agent}]*\n{truncated}")

        result = "\n\n".join(lines)
        if len(result) > max_length:
            result = result[:max_length] + "\n...(truncated)"
        return result
