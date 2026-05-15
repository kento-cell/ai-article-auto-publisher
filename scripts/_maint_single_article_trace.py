"""Maintenance: trace a SINGLE article through Phase 2 manually,
logging at every step so we can see where time is spent and what
truncations happen.

Run with:
  py scripts/_maint_single_article_trace.py
"""
from __future__ import annotations
import os, sys, time, json
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
os.environ.setdefault("USE_CHATGPT_IMAGES", "0")
os.environ.setdefault("CHATGPT_VISION_EVAL", "0")
os.environ.setdefault("C_RESCUE_ENABLED", "false")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("maint")


def main() -> int:
    # Fabricate a minimal article candidate so we don't need full
    # collect/rank pipeline. Use the seeded RAG topic content from
    # knowledge_topics.json so this is realistic.
    article = {
        "title": "【保存版】RAG の作り方 2026 — 10 種類のパターンを chromadb で実運用してわかった使い分け",
        "platform": "note",
        "trend_score": 80.0,
        "source": "knowledge_topics",
        "url": "",
        "content": (
            "RAG の作り方を Naive RAG / Re-ranking / Hybrid Search / "
            "CRAG / GraphRAG / Self-RAG / Agentic RAG / Long-context vs RAG / "
            "Multimodal RAG の 10 種類のパターンで網羅的に整理する。"
            "筆者が chromadb + intfloat/multilingual-e5-base で実運用する中で踏んだ"
            "事案 (sim 0.92 で素通り、MD5 同一画像、Lake Tahoe スコープ逸脱) を"
            "一次情報として埋め込む。"
        ),
    }

    log.info("=== STEP 1: load config ===")
    from main import load_config
    config = load_config()
    log.info("config loaded, %d top-level keys", len(config))

    log.info("=== STEP 2: load token manager + LLM ===")
    from utils.token_manager import TokenManager
    from main import _init_llm
    token_manager = TokenManager()
    claude, local_llm, use_local = _init_llm(token_manager)
    log.info("llm ready: use_local=%s default_model=%s",
             use_local, local_llm.default_model if local_llm else "N/A")

    log.info("=== STEP 3: load prompts ===")
    import yaml
    prompts = yaml.safe_load(
        (_REPO / "config" / "prompts.yaml").read_text(encoding="utf-8")
    )
    log.info("prompts loaded, keys=%s", list(prompts.keys())[:6])

    log.info("=== STEP 4: pick prompt template + structure ===")
    template = prompts.get("note_article_prompt", "")
    log.info("template length: %d chars", len(template))

    log.info("=== STEP 5: build full prompt (writer input) ===")
    # The actual generation injects via the template's format placeholders.
    # Just substitute minimally to see total prompt length.
    sample_prompt = template.format(
        title=article["title"],
        source=article["source"],
        url="https://example.com",
        trend_score=article["trend_score"],
        content=article["content"][:600],
    )
    log.info("FULL prompt length: %d chars (~%d tokens for JP)",
             len(sample_prompt), len(sample_prompt) * 3 // 4)
    if len(sample_prompt) > 8192 * 3 // 4:
        log.warning("prompt may exceed num_ctx=8192 token budget — Writer may truncate!")

    log.info("=== STEP 6: invoke writer LLM (this is the long part) ===")
    t0 = time.time()
    response = local_llm.generate(sample_prompt, temperature=0.7)
    elapsed = time.time() - t0
    log.info("LLM responded in %.1fs, output %d chars (~%d tokens)",
             elapsed, len(response), len(response) * 3 // 4)

    # Write the output for inspection
    out_path = _REPO / "data" / "_maint_trace_writer_output.md"
    out_path.write_text(response, encoding="utf-8")
    log.info("output saved to %s", out_path)

    log.info("=== STEP 7: structural snapshot ===")
    import re
    h2 = len(re.findall(r"^##\s", response, re.MULTILINE))
    bold_pseudo = len(re.findall(r"^\*\*\d+\.\s", response, re.MULTILINE))
    tables = len(re.findall(r"^\|[\s\-:]+\|", response, re.MULTILINE))
    images = len(re.findall(r"!\[", response))
    log.info("H2=%d, bold-pseudo (need post-processor)=%d, tables=%d, images=%d",
             h2, bold_pseudo, tables, images)

    log.info("=== STEP 8: post-processor effect ===")
    from main import _fix_bold_pseudo_headings, _ensure_min_visual
    fixed = _fix_bold_pseudo_headings(response)
    h2_after = len(re.findall(r"^##\s", fixed, re.MULTILINE))
    log.info("after H2 post-processor: H2=%d (was %d)", h2_after, h2)
    fixed, injected = _ensure_min_visual(fixed, article["title"])
    tables_after = len(re.findall(r"^\|[\s\-:]+\|", fixed, re.MULTILINE))
    log.info("after visual post-processor: tables=%d, injected=%s",
             tables_after, injected)

    log.info("=== STEP 9: sanitize ===")
    from generators.content_sanitizer import sanitize
    cleaned, removed = sanitize(fixed)
    log.info("sanitize removed %d artifacts: %s", len(removed), removed[:3])

    log.info("=== STEP 10: objective score ===")
    from generators.objective_scorer import ObjectiveScorer
    scorer = ObjectiveScorer()
    obj = scorer.score(cleaned, {
        "sources": [],
        "forbidden_phrases": config.get("evidence", {}).get("forbidden_phrases", []),
        "chain_blacklist": [],
        "title": article["title"],
        "platform": article["platform"],
    })
    log.info("objective: pass=%s grade=%s",
             obj.get("objective_pass"), obj.get("overall_grade"))
    if not obj.get("objective_pass"):
        log.info("blocking_issues: %s", obj.get("blocking_issues"))
    metrics = obj.get("metrics") or {}
    for name in ("word_count", "visual_count", "heading_structure",
                 "citation_count", "title_fulfillment"):
        m = metrics.get(name, {})
        log.info("  %s: %s — %s", name, m.get("grade"), m.get("reason", "")[:80])

    log.info("=== DONE ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
