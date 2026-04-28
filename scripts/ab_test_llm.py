"""A/B compare LLM models on the same prompt.

Generates content with both Model A and Model B for one or more
prompts, then reports length, latency, and a quick objective check
(JSON-parseable for scorer prompts, basic Markdown structure for
writer prompts). Saves outputs side-by-side for human review.

Usage::

    py scripts/ab_test_llm.py writer
    py scripts/ab_test_llm.py summarizer
    py scripts/ab_test_llm.py scorer

The two models compared come from env vars or sensible defaults:

    AB_MODEL_A   default: gemma3:12b
    AB_MODEL_B   default: qwen2.5:14b
    AB_OUT_DIR   default: data/ab_tests/<timestamp>/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from dotenv import load_dotenv
load_dotenv()

from generators.local_llm import LocalLLM


# ---------------------------------------------------------------------
# Test prompts per task
# ---------------------------------------------------------------------

WRITER_PROMPTS = [
    {
        "name": "tech_explainer",
        "prompt": """以下のテーマで日本語の技術解説記事を1500字程度で書いてください。
テーマ: 「Anthropic Claude Code が他のAIコーディングアシスタントと違う3つの理由」
- 出力はMarkdown
- H2 (##) 見出しを3つ以上
- コードブロックや箇条書きを含めて構造化
- 記事末尾に出典(架空のURL禁止、書けない場合は省略)
""",
    },
    {
        "name": "lifestyle_listicle",
        "prompt": """以下のテーマで日本語のリスト形式記事を1500字程度で書いてください。
テーマ: 「韓国で今バズっているコスメブランド5選 (2025年版)」
- 出力はMarkdown
- ブランド毎にH3 (###) 見出し
- 各ブランド: 特徴 / 推し製品 / 購入経路 / 注意点 を含める
- チェーン店紹介は避け、個人発信や独立ブランド優先
""",
    },
]

SUMMARIZER_PROMPT_TEMPLATE = """\
以下は英語のAI業界ニュースのタイトルと要約です。
日本語で 3〜5 行 (合計 250 文字以内) に再構成してください。

含めるべき要素:
1. 何が起きたか (1行)
2. 重要な数字・モデル名・固有名詞 (原文ママ)
3. 業界への含意 / なぜ注目すべきか (1〜2行)

タイトル: {title}
原文要約: {raw}

日本語要約:
"""

SUMMARIZER_PROMPTS = [
    {
        "name": "anthropic_funding",
        "prompt": SUMMARIZER_PROMPT_TEMPLATE.format(
            title="Anthropic raises $13B Series F at $183B valuation",
            raw=(
                "Anthropic announced the closing of a $13B Series F at "
                "a $183B post-money valuation. Led by ICONIQ with "
                "Lightspeed, Menlo Ventures, and Google. Will fund "
                "Claude Opus 5 development and enterprise expansion. "
                "ARR up from $1B to $5B during the year. Major "
                "customers: AWS, Google Cloud, 30,000+ enterprises."
            ),
        ),
    },
    {
        "name": "openai_pricing",
        "prompt": SUMMARIZER_PROMPT_TEMPLATE.format(
            title="OpenAI cuts gpt-5 image generation API price by 40%",
            raw=(
                "OpenAI today reduced the per-image price of gpt-image-1 "
                "from $0.04 to $0.024 (HD) and $0.17 to $0.10 (4K). "
                "Effective immediately. The cut tracks a 60% drop in "
                "inference cost from new Blackwell GPU clusters. "
                "Competing with Google's gemini-2.5-flash-image at $0.039."
            ),
        ),
    },
]

SCORER_PROMPTS = [
    {
        "name": "scorer_json_stress",
        "prompt": """You are a strict article reviewer. Evaluate the article on 5 dimensions.
Return ONLY a JSON object — no Markdown, no prose, no code fences.

Dimensions: originality, accuracy, readability, engagement, title_fulfillment.
Each dimension MUST have: grade (A/B/C), reason (>=20 chars).

Article:
タイトル: 「Claude Codeで爆速開発、効率5倍」
本文: ClaudeCodeを使うと開発が速くなります。便利です。CLIから動きます。
試してみたら良かったです。これからも使い続けます。

Output JSON:
""",
    },
]

PROMPT_SETS = {
    "writer":     WRITER_PROMPTS,
    "summarizer": SUMMARIZER_PROMPTS,
    "scorer":     SCORER_PROMPTS,
}


# ---------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------

def run_one(model: str, prompt: str, temperature: float) -> dict:
    """Generate once and return latency + output + basic stats."""
    llm = LocalLLM(default_model=model)
    t0 = time.time()
    try:
        out = llm.generate(prompt, temperature=temperature)
        ok = True
        err = ""
    except Exception as exc:  # noqa: BLE001
        out = ""
        ok = False
        err = str(exc)
    latency = time.time() - t0
    return {
        "model": model,
        "ok": ok,
        "error": err,
        "latency_sec": round(latency, 2),
        "output_chars": len(out),
        "output": out,
    }


def quick_check(task: str, output: str) -> dict:
    """Lightweight sanity checks per task type."""
    checks: dict[str, bool] = {}
    if task == "writer":
        checks["has_h2"]    = "## " in output or "##　" in output
        checks["has_list"]  = any(line.lstrip().startswith(("-", "*", "1."))
                                   for line in output.splitlines())
        checks["min_length"] = len(output) >= 800
    elif task == "summarizer":
        checks["multi_line"] = output.count("\n") >= 2
        checks["under_cap"]  = len(output) <= 600
        checks["non_empty"]  = len(output.strip()) > 0
    elif task == "scorer":
        try:
            # Try to find a JSON object
            start = output.find("{")
            end = output.rfind("}")
            data = json.loads(output[start:end + 1]) if start != -1 else {}
            for dim in ("originality", "accuracy", "readability",
                        "engagement", "title_fulfillment"):
                checks[f"has_{dim}"] = isinstance(data.get(dim), dict)
        except Exception:  # noqa: BLE001
            checks["json_parseable"] = False
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "task",
        choices=["writer", "summarizer", "scorer"],
        help="Which prompt set to test.",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.7,
        help="Sampling temperature (default 0.7).",
    )
    args = parser.parse_args()

    model_a = os.environ.get("AB_MODEL_A", "gemma3:12b")
    model_b = os.environ.get("AB_MODEL_B", "qwen2.5:14b")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(os.environ.get(
        "AB_OUT_DIR", str(ROOT / "data" / "ab_tests" / timestamp)
    ))
    out_dir.mkdir(parents=True, exist_ok=True)

    prompts = PROMPT_SETS[args.task]
    summary = {"task": args.task, "model_a": model_a, "model_b": model_b,
               "items": []}

    for spec in prompts:
        name = spec["name"]
        prompt = spec["prompt"]
        print(f"\n=== {name} ({args.task}) ===")
        print(f"  A={model_a}  B={model_b}  temp={args.temperature}")

        a = run_one(model_a, prompt, args.temperature)
        b = run_one(model_b, prompt, args.temperature)

        a_checks = quick_check(args.task, a["output"])
        b_checks = quick_check(args.task, b["output"])

        item = {
            "name": name,
            "a": {
                "model": a["model"], "ok": a["ok"], "err": a["error"],
                "latency_sec": a["latency_sec"],
                "output_chars": a["output_chars"], "checks": a_checks,
            },
            "b": {
                "model": b["model"], "ok": b["ok"], "err": b["error"],
                "latency_sec": b["latency_sec"],
                "output_chars": b["output_chars"], "checks": b_checks,
            },
        }
        summary["items"].append(item)

        # Side-by-side outputs for manual review
        (out_dir / f"{name}__A_{model_a.replace(':', '_')}.md").write_text(
            f"# {name}  ({model_a})\n\n"
            f"latency: {a['latency_sec']}s, chars: {a['output_chars']}, "
            f"checks: {json.dumps(a_checks, ensure_ascii=False)}\n\n"
            f"---\n\n{a['output']}\n",
            encoding="utf-8",
        )
        (out_dir / f"{name}__B_{model_b.replace(':', '_')}.md").write_text(
            f"# {name}  ({model_b})\n\n"
            f"latency: {b['latency_sec']}s, chars: {b['output_chars']}, "
            f"checks: {json.dumps(b_checks, ensure_ascii=False)}\n\n"
            f"---\n\n{b['output']}\n",
            encoding="utf-8",
        )

        print(f"  A: {a['latency_sec']}s, {a['output_chars']} chars, checks={a_checks}")
        print(f"  B: {b['latency_sec']}s, {b['output_chars']} chars, checks={b_checks}")

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nResults saved to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
