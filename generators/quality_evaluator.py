"""
品質評価モジュール

生成された記事の品質を5軸（独自性・正確性・可読性・引用・実用性）で評価する。
LLMによる評価結果をパースし、閾値判定を行う。
"""

import json
import re
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

EVALUATION_DIMENSIONS = [
    "originality",
    "accuracy",
    "readability",
    "citation",
    "practicality",
]


class QualityEvaluator:
    """記事品質を評価するクラス。"""

    def __init__(self, prompts_path: str = "config/prompts.yaml"):
        """初期化。

        Args:
            prompts_path: プロンプト設定ファイルパス。
        """
        self.prompt_template = self._load_evaluation_prompt(prompts_path)

    def _load_evaluation_prompt(self, prompts_path: str) -> str:
        """評価用プロンプトを読み込む。"""
        try:
            import yaml
            with open(prompts_path, "r", encoding="utf-8") as f:
                prompts = yaml.safe_load(f)
            return prompts.get("quality_evaluation_prompt", "")
        except Exception as e:
            logger.warning("プロンプト読み込み失敗: %s", e)
            return ""

    def evaluate(
        self,
        article: str,
        evaluator_fn: Callable[[str], str],
    ) -> dict:
        """記事を評価する。

        Args:
            article: 評価対象の記事テキスト。
            evaluator_fn: プロンプトを受け取りLLM応答を返す関数。

        Returns:
            評価結果dict。スコア、合否、フィードバックを含む。
        """
        prompt = self.prompt_template.format(article=article)

        try:
            response = evaluator_fn(prompt)
            scores = self.parse_evaluation(response)
            logger.info(
                "品質評価完了: 合計=%d/50, 合格=%s",
                scores.get("total", 0),
                scores.get("pass", False),
            )
            return scores
        except Exception as e:
            logger.error("品質評価エラー: %s", e)
            return self._default_scores()

    def parse_evaluation(self, response: str) -> dict:
        """LLM応答から評価JSONを抽出・パースする。

        Args:
            response: LLMの応答テキスト。

        Returns:
            パースされた評価結果dict。
        """
        json_str = self._extract_json(response)
        if not json_str:
            logger.warning("JSON抽出失敗。デフォルトスコアを返します。")
            return self._default_scores()

        try:
            data = json.loads(json_str)
            return self._validate_scores(data)
        except json.JSONDecodeError as e:
            logger.warning("JSONパースエラー: %s", e)
            return self._default_scores()

    def _extract_json(self, text: str) -> Optional[str]:
        """テキストからJSON部分を抽出する。"""
        # コードブロック内のJSONを探す
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            return code_block.group(1)

        # 直接JSONオブジェクトを探す
        json_match = re.search(r"\{[^{}]*\"scores\"[^{}]*\{.*?\}.*?\}", text, re.DOTALL)
        if json_match:
            return json_match.group(0)

        return None

    def _validate_scores(self, data: dict) -> dict:
        """スコアデータを検証・正規化する。"""
        scores = data.get("scores", {})
        validated = {}

        for dim in EVALUATION_DIMENSIONS:
            value = scores.get(dim, 0)
            validated[dim] = max(0, min(10, int(value)))

        total = sum(validated.values())
        return {
            "scores": validated,
            "total": total,
            "pass": data.get("pass", total >= 25),
            "feedback": data.get("feedback", ""),
            "should_regenerate": data.get("should_regenerate", total < 20),
        }

    def _default_scores(self) -> dict:
        """デフォルト（評価失敗時）のスコアを返す。"""
        scores = {dim: 0 for dim in EVALUATION_DIMENSIONS}
        return {
            "scores": scores,
            "total": 0,
            "pass": False,
            "feedback": "評価を実行できませんでした。",
            "should_regenerate": True,
        }

    def meets_threshold(self, scores: dict, min_score: int = 45) -> bool:
        """品質基準を満たすか判定する。

        Args:
            scores: evaluate()の戻り値。
            min_score: 最低合格スコア（/50）。

        Returns:
            基準を満たす場合True。
        """
        total = scores.get("total", 0)
        return total >= min_score

    def get_feedback(self, scores: dict) -> str:
        """人間可読なフィードバックを生成する。

        Args:
            scores: evaluate()の戻り値。

        Returns:
            フィードバック文字列。
        """
        lines = [f"品質スコア: {scores.get('total', 0)}/50"]
        dim_labels = {
            "originality": "独自性",
            "accuracy": "正確性",
            "readability": "可読性",
            "citation": "引用",
            "practicality": "実用性",
        }

        for dim, label in dim_labels.items():
            value = scores.get("scores", {}).get(dim, 0)
            bar = "█" * value + "░" * (10 - value)
            lines.append(f"  {label}: {bar} {value}/10")

        if scores.get("feedback"):
            lines.append(f"\n改善点: {scores['feedback']}")

        if scores.get("should_regenerate"):
            lines.append("→ 再生成を推奨します。")

        return "\n".join(lines)
