# LLM Migration Guide

## 目的

`generators/local_llm.py` の単一モデル運用 (`gemma3:12b`) から、
**タスク別モデル選択** に移行可能な構成へ拡張する。

主要な動機:
- **Writer/Scorer 分離** — 同モデルが書き手と評価者を兼ねると評価バイアスが入るため、別モデルで切り分けたい
- **モデル比較・段階移行** — 環境変数1つでロールバック可能、A/Bテスト可能
- **将来の品質向上** — Qwen2.5/Qwen3 等への部分移行で日本語精度・JSON安定性を検証可能

## アーキテクチャ

```
generators/llm_config.py        ← 新規。タスク→モデル名のマッピング
generators/local_llm.py         ← 既存。Ollama API クライアント (変更なし)
```

呼び出し側は `LocalLLM()` を直接生成する代わりに `get_llm("writer")` を経由。

### タスク種別

| タスク     | 用途                       | env var               | デフォルト   |
|-----------|---------------------------|----------------------|------------|
| writer    | 記事本文生成               | `LLM_MODEL_WRITER`    | gemma3:12b |
| scorer    | 主観スコアリング           | `LLM_MODEL_SCORER`    | gemma3:12b |
| summarizer| catchup要約               | `LLM_MODEL_SUMMARIZER`| gemma3:12b |
| hashtag   | ハッシュタグ生成           | `LLM_MODEL_HASHTAG`   | gemma3:12b |
| regenerator| 再生成マルチエージェント | `LLM_MODEL_REGENERATOR`| gemma3:12b |

## 段階移行プラン

### Phase 0: 現状維持 (←現在ここ)

env var 未設定で全タスクが `gemma3:12b`。挙動は移行前と完全に同じ。

### A/B テスト結果 (2026-04-27)

`scripts/ab_test_llm.py` を全タスクで実行した結果:

| タスク     | 勝者          | 根拠                                                |
|-----------|--------------|---------------------------------------------------|
| writer    | gemma3:12b   | 長文構造化 / 箇条書き / 固有名詞網羅 / 速度1.4倍    |
| scorer    | gemma3:12b   | 入れ子JSON schema完全遵守 (qwen2.5はフラット化破壊) |
| summarizer| 引き分け     | 構造=gemma3 / 固有名詞網羅=qwen2.5                  |

**現時点での結論**: 当ツールの既存プロンプトは Gemma3 向けにチューニング済みのため、
モデル単純差し替えでは品質向上が見込めない。

### 将来モデル切替を再検討するトリガー

以下のいずれかが発生した時に再評価:

1. **Qwen3 のLLM-jp公式ベンチ掲載** — Gemma3 を有意に超える数値が公開された場合
2. **プロンプトの Qwen 向け再チューニング** — 入れ子JSON要求を平坦化、明示的改行指示を追加
3. **VRAM 増強** — qwq:32b や qwen2.5:32b が動くようになった場合の scorer 強化検証

### Phase 1: Shadow run (再検討トリガー後の手順)

```bash
# .env に追加 (低リスク領域から)
LLM_MODEL_SUMMARIZER=qwen2.5:14b
```

catchup要約のみ qwen2.5 で運用 → 1週間モニタ → A/B 結果と整合確認

### Phase 2: Writer/Scorer 分離 (Shadow successful時)

```bash
LLM_MODEL_WRITER=qwen2.5:14b
LLM_MODEL_SCORER=gemma3:12b      # ← 別モデルにすることでバイアス回避
```

### Phase 3: 全面移行 (慎重)

`scripts/ab_test_llm.py` で20本程度A/B生成 → 主観/客観スコア比較 →
有意な品質向上が確認できた時のみ移行

## ロールバック手順

問題発生時は `.env` から `LLM_MODEL_*` 行を全削除して
パイプライン再起動するだけで gemma3:12b 単一運用に戻る。

```bash
# 緊急ロールバック
sed -i '/^LLM_MODEL_/d' .env
# bot 再起動
```

## A/B テスト

```bash
# summarizer タスクで gemma3 vs qwen2.5:14b 比較
py scripts/ab_test_llm.py summarizer

# writer
py scripts/ab_test_llm.py writer

# scorer (JSON出力安定性)
py scripts/ab_test_llm.py scorer
```

結果は `data/ab_tests/<timestamp>/` に
- 各モデルの出力 (markdown, 人間レビュー用)
- `summary.json` (latency, char count, sanity checks)

## 観測ポイント

主観スコアラーに `_parse_attempts` フィールド追加。
モデル交換時にJSON出力の安定性が変わる場合、ログ・Sheetsから検出可能。

```
2026-04-27 ... [INFO] Subjective evaluation complete: pass=True, attempts=1
                                                                    ^^^^^^^^^^
                                                                    1=正常、2=リトライ発生
```

## VRAM 制約 (現環境)

GPU: NVIDIA GeForce RTX 3070 (8GB VRAM)

| モデル | サイズ | 動作可否 |
|---|---|---|
| gemma3:12b      | 8.1GB | ✓ |
| qwen2.5:14b     | 9.0GB | ✓ (一部 system RAM 利用) |
| qwen2.5:7b      | 4.7GB | ✓ (高速) |
| qwen2.5:32b     | ~20GB | ✗ (VRAM不足) |
| qwq:32b         | ~20GB | ✗ (VRAM不足) |
| qwen3:14b       | ~9GB  | ✓ (公式bench未掲載のため評価保留) |

将来 GPU 増強したら qwq:32b を `scorer` に投入することで主観評価精度の向上余地あり。

## 関連ファイル

- `generators/llm_config.py` — タスク→モデルマッピング
- `generators/local_llm.py` — Ollama クライアント
- `generators/subjective_evaluator.py` — JSON schema retry 追加
- `main.py` `_init_llm()` — writer モデルで初期化
- `catchup/summarizer.py` — summarizer モデルで初期化
- `scripts/ab_test_llm.py` — A/B テストハーネス
