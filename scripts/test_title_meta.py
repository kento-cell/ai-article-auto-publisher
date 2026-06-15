"""Unit tests for title meta-artifact stripping (main._strip_title_meta /
main._extract_japanese_title).

Background: the publish title is extracted from the article body H1, which
bypasses the quality gate. An LLM echoed the prompt's title-length budget
into the H1 and '（35文字）' shipped live on note nd704d3e75847 (2026-06-15).
These tests pin the sanitizer's behaviour, including the false-positive and
boundary cases raised in the 2026-06-15 Codex review.

Run: PYTHONIOENCODING=utf-8 py scripts/test_title_meta.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402

_FAILS: list[str] = []


def _eq(got: str, want: str, label: str) -> None:
    status = "PASS" if got == want else "FAIL"
    if got != want:
        _FAILS.append(label)
    print(f"  [{status}] {label}: {got!r}")


def test_strip() -> None:
    print("[1] _strip_title_meta")
    f = main._strip_title_meta
    # core artifact removal (the live incident)
    _eq(f("この文具ガジェットは嘘だった。（35文字）"),
        "この文具ガジェットは嘘だった", "（N文字）+句点")
    # range form, half-width parens
    _eq(f("ローカルLLMは嘘だった (35〜45文字)"),
        "ローカルLLMは嘘だった", "(N〜M文字) 半角括弧")
    # 【N文字】 bracket form
    _eq(f("タイトル本体【70文字】"), "タイトル本体", "【N文字】")
    # suffix variants
    _eq(f("要約テスト（35文字以内）"), "要約テスト", "文字以内")
    _eq(f("要約テスト（35文字程度）"), "要約テスト", "文字程度")
    # outer closing quote preserved
    _eq(f("「シール交換は嘘だった（35文字）」"),
        "「シール交換は嘘だった」", "外側引用符を保持")
    # NO artifact -> untouched, including legit trailing punctuation
    _eq(f("なぜ失敗したのか。"), "なぜ失敗したのか。", "句点は無改変で保持")
    _eq(f("普通のタイトル【保存版】"), "普通のタイトル【保存版】", "正規ブラケット保持")
    _eq(f("Galaxy S27 Proのバッテリー徹底解説"),
        "Galaxy S27 Proのバッテリー徹底解説", "通常タイトル無改変")
    # only-artifact -> empty (so extractor falls through)
    _eq(f("（35文字）"), "", "注記のみ→空")


def test_extract() -> None:
    print("[2] _extract_japanese_title")
    g = main._extract_japanese_title
    # H1 with artifact
    _eq(g("# 携帯ハサミは嘘だった。（35文字）\n本文"),
        "携帯ハサミは嘘だった", "H1 から注記除去")
    # artifact-only H1 must fall through to the valid H2
    _eq(g("# （35文字）\n## 本物のタイトルはこちら\n本文"),
        "本物のタイトルはこちら", "注記のみ H1→次候補へ fall through")
    # boundary: 96-char title + （35文字） must not leave a fragment
    long = "あ" * 96
    out = g(f"# {long}（35文字）\n本文")
    ok = "（" not in out and "文字" not in out and out == long[:100]
    _eq("clean" if ok else out, "clean", "96字+注記の境界断片なし")


if __name__ == "__main__":
    test_strip()
    test_extract()
    if _FAILS:
        print(f"\nFAIL: {len(_FAILS)} case(s): {_FAILS}")
        sys.exit(1)
    print("\nPASS: all title-meta cases OK")
