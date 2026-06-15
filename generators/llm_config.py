"""Task-specific LLM model selection.

Centralises which Ollama model is used for each pipeline task.
The default is ``gemma4:e4b`` (2026-06-15); a per-task ``LLM_MODEL_*``
env var overrides it, making rollout/rollback trivial.

Tasks:
    writer      — main article body generation
    scorer      — subjective evaluator (separate from writer to avoid
                  self-grading bias when both run the same model)
    summarizer  — catchup digest summary
    hashtag     — note/Zenn hashtag generation
    regenerator — multi-agent regeneration loop

Env var pattern: ``LLM_MODEL_<TASK>`` (uppercase).
Example::

    LLM_MODEL_WRITER=qwen2.5:14b
    LLM_MODEL_SCORER=gemma3:12b      # keep gemma to separate from writer
    LLM_MODEL_SUMMARIZER=qwen2.5:14b
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Default model for every task. Keep this aligned with the existing
# ``DEFAULT_MODEL`` in ``local_llm.py``. 2026-06-15: flipped to gemma4:e4b so
# all five tasks (and any no-arg LocalLLM() bypass site) default to gemma4 —
# the per-task LLM_MODEL_* env vars still override when set.
_DEFAULT_MODEL = "gemma4:e4b"

_TASK_MODELS: dict[str, str] = {
    "writer":      os.environ.get("LLM_MODEL_WRITER",      _DEFAULT_MODEL),
    "scorer":      os.environ.get("LLM_MODEL_SCORER",      _DEFAULT_MODEL),
    "summarizer":  os.environ.get("LLM_MODEL_SUMMARIZER",  _DEFAULT_MODEL),
    "hashtag":     os.environ.get("LLM_MODEL_HASHTAG",     _DEFAULT_MODEL),
    "regenerator": os.environ.get("LLM_MODEL_REGENERATOR", _DEFAULT_MODEL),
}


def get_model(task: str) -> str:
    """Resolve the model name for a given pipeline task.

    Falls back to the default model when an unknown task is requested.
    """
    return _TASK_MODELS.get(task, _DEFAULT_MODEL)


def get_llm(task: str = "writer", **kwargs):
    """Construct a :class:`LocalLLM` configured for *task*.

    Imported lazily so this module stays cheap to import (no requests
    network setup, no env validation) for callers that only need the
    model-name lookup.
    """
    from generators.local_llm import LocalLLM
    model = get_model(task)
    logger.debug("get_llm(task=%s) -> model=%s", task, model)
    return LocalLLM(default_model=model, **kwargs)


def model_summary() -> dict[str, str]:
    """Return a snapshot of resolved task→model mapping (for logging)."""
    return dict(_TASK_MODELS)
