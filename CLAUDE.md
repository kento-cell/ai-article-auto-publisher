# Claude Code — AI記事自動生成システム

## ⚡ 自走モード（このファイルを読んだら自動で行動開始）

このリポジトリを開いたら、最小コストで状況を把握して自走する。

### 起動時の必読 (これだけでOK、 詳細は後追い)

1. **`docs/sessions/STATE.md`** — 現在の状態 + Next Actions (≤60 行)
2. **memory 索引** (auto-loaded、 個別 file は必要時のみ Read)

詳細履歴 (`docs/sessions/JOURNAL.md` / `docs/sessions/2026-05_archive.md`)
は **STATE.md だけで足りない時に** Read。 推奨は `Agent` ツールで
`session-reader` subagent を呼ぶ (Haiku、 別 200K window、 25K tokens を
400 tokens に圧縮)。

長期参照 (任意、 必要に応じて):
- `AGENTS.md` — エージェント設計 (Researcher/Strategist/Writer/Critic/Coordinator)
- `docs/requirements.md` — 要件定義
- `docs/sessions/20260407_*` — 初期設計判断 (4-7 時点のスナップ)

### 起動後の自動アクション

1. `git pull` で最新コードを取得
2. STATE.md を確認 (in-flight / Next Actions / Known Issues)
3. デグレチェック: `py -c "import main"` (詳細は ## デグレチェック手順 節)
4. STATE.md の「Next Actions」 を順に実行 — 終わったら STATE.md を bump

---

## 🔴 ツールの理念（絶対に守ること）

**タイトルは攻めていい。グレーギリギリでも合法なら構わない。**
**ただし大々的に謳った以上、中身は絶対に濃くなければならない。**
**タイトル負け = 読者への裏切り = 絶対禁止。**

これは全エージェント、全プロンプト、全スコアリングに浸透済みの最上位ルール。

---

## プロジェクト概要

Zenn (技術記事) と note (一般向け) に高品質な記事を自動生成・投稿するシステム。
5 つの専門エージェント (Researcher / Strategist / Writer / Critic / Coordinator)
がディスカッションして品質を担保する。

### ターゲットコンテンツ

**Zenn (有料記事・技術系プレミアム):** AI ツール実践ガイド / 最新論文解説 /
AI × マネタイズ実務 / エージェント時代の新スキル

**note (バズるコンテンツ):** 韓国トレンド・美容・K-POP / 隠れた名店グルメ
(個人店のみ) / コーヒー・バリスタ文化 / 美意識高め層向け自分磨き / AI 副業

### 絶対ルール

- チェーン店は紹介しない (個人店・隠れた名店のみ)
- 架空の店名・住所・メニュー名は書かない (元ソースにある情報のみ)
- 有名人言及は公式ソース (Tier1-2) がある場合のみ
- タイトルで煽った内容は本文で必ず回収する

---

## デグレチェック手順

コード変更後、必ず以下を確認:

```bash
# 1. インポートチェック
py -c "import main"
py -c "from generators.objective_scorer import ObjectiveScorer"
py -c "from generators.subjective_evaluator import SubjectiveEvaluator"
py -c "from generators.score_aggregator import ScoreAggregator"
py -c "from utils.article_store import ArticleStore"
py -c "from utils.sheets_manager import SheetsManager"

# 2. ハルシ deny regression (40 deny + 7 sanitizer + 3 RAG)
py scripts/test_hallucination_deny.py

# 3. 収集テスト (API 不要)
py main.py --collect-only

# 4. ドライラン (Ollama 必要、 Sheets / 投稿なし)
py main.py --dry-run
```

---

## アーキテクチャ

### パイプライン

```
--generate:
  収集 (arXiv + RSS 日本語 + RSS 韓国 + Reddit)
    → トレンドスコアでランク付け
    → 構成パターン自動選択 (listicle / trend_report / howto / tutorial 等)
    → LLM 記事生成 (プロンプトに構成パターン注入)
    → カバー画像自動生成
    → 客観スコアリング (引用数 / Tier 比率 / 視覚要素 / チェーン店検出)
    → 主観スコアリング (独自性 / 正確性 / 可読性 / 引き込み)
    → 集約判定 (A/B/C、 C は自動却下)
    → ArticleStore (data/articles/*.json) + Sheets (⏳承認待ち) + Gmail

--publish:
  Sheets から ✅承認 を取得
    → ArticleStore からコンテンツ読み込み
    → ハッシュタグ自動生成
    → Zenn: Git push (published: true、 slow-walk queue で順次公開)
    → note: Selenium 投稿 (価格は A/B/C から自動算出)
    → Slack + Gmail 通知
```

### スコアリング (2 層)

- **客観 (足切り)**: エビデンス Tier1-2 率 / 引用数 / 引用形式 / 視覚要素 /
  禁止フレーズ / チェーン店 → A/B/C。 客観 C が 1 つでもあれば総合 C で自動却下
- **主観 (LLM 評価、 根拠必須)**: 独自性 / 正確性 / 可読性 / 引き込み → 各 A/B/C
- **総合**: `min(客観最低値, 主観平均)`

### note 有料化

`A+A 証拠 → ¥1,980` / `A+B → ¥980` / `B+A → ¥500` / `B+B → ¥300` / `その他 → 無料`

### スキル定義

`.claude/skills/` と `.codex/skills/` に同一内容で配置 (更新時は両方同期)。
- パイプライン: core / collection / generation / quality-gate / publishing / self-improvement
- エージェント: researcher / strategist / writer / critic / coordinator

---

## ファイル構成 (主要)

```
main.py                       # メインパイプライン
bot/                          # Slack Bot (詳細 bot/CLAUDE.md)
collectors/                   # arxiv / reddit / rss / trend_detector
generators/                   # scorer / evaluator / aggregator / image / hashtag
publishers/                   # zenn / note / gmail / slack  (罠 publishers/CLAUDE.md)
utils/                        # article_store / sheets_manager / token_manager
config/                       # prompts.yaml / settings.yaml.example
scripts/                      # one-shot + 定常運用 (詳細 scripts/CLAUDE.md)
docs/sessions/                # STATE.md (current) / JOURNAL.md (today) / archive/
.claude/agents/               # session-reader subagent ほか
.claude/skills/               # パイプライン + エージェント skill 定義
```

---

## 開発時の注意

- 品質スコアは A/B/C グレード制 (旧数値スコアは廃止)
- Mermaid オンラインレンダリングは無効化 (記事内容の外部送信防止)
- 画像: stock (CC0 / Unsplash / Pexels / AI 生成 / Pillow バナー) は paid 可、
  店舗・商品の借用画像 (公式 SNS 等) は free 限定
  (`main.py::_has_borrowed_image_attribution` が marker 検知して price=¥0 強制)
- チェーン店ブラックリストは `config/settings.yaml` の
  `evidence.gourmet_rules.chain_blacklist`
- 構成パターンは `config/prompts.yaml` の `article_structures` + `structure_selection`

---

## Monitor / バックグラウンドタスクの後始末

Claude Code の `Monitor` (`tail -F ... | grep ...`) を使った後は、
`TaskStop` だけだと Windows 上で子プロセス (`tail.exe` / `grep.exe`) が
孤児化して残る (シグナル伝播)。

ターン終了前に必ず:

```powershell
Get-Process tail,grep -ErrorAction SilentlyContinue | Stop-Process -Force
```

何もぶら下がっていなければ no-op。
