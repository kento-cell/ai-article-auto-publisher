# Note 自動生成パイプライン 再設計提案

_作成: 2026-05-14 (10 連続 generate で note 0 件合格を観測した日)_

## 1. 問題の核心 — ソースと note 主流の根本的ミスマッチ

**今の私たちのパイプライン:** Reddit / Hacker News / 海外 RSS のニュースを Writer に
「ネタ元」として渡し、2200+ 文字の解説記事を生成 → note 投稿。

**note 主流コンテンツ (2025-2026 web 調査結果):**
- 主流は **一次情報・生の体験記録・失敗からの学び**
  ([noteup_iinkai](https://note.com/noteup_iinkai/n/nfe90356c527a),
  [happy_brains](https://note.com/happy_brains/n/n0317f0037edd))
- 売れジャンル: 副業体験談+収益公開 / ChatGPT実体験 / 占い・スピ / SNS運用 /
  HARM (Health/Ambition/Relationship/Money) 悩み系
  ([dapper_poppy7392](https://note.com/dapper_poppy7392/n/n9de0a55ddc68))
- 二次的なまとめ記事はランキング外

**つまり:** ニュース直訳の解説記事は note の主流フォーマットと **ジャンルが違う**。
Reddit の話題を翻訳しても note では響かない。**この点に取り組まずに長さや視覚要素を
調整しても本質的に伸びない。**

## 2. 評価ロジックの note 現実との乖離

note 公式 30万件分析:
- **文字数と売上の相関 = ほぼゼロ** (実用系 -0.023, 読み物系 0.011)
  ([note株式会社](https://note.jp/n/n8522197d1ced))
- **4,000字超は離脱リスク +18%**
- 上位は **画像/動画率 70%+ が ¥800 妥当ライン** ≈ H2 ごとに 1 枚
- 「長ければ売れる」は神話

**現状の objective_scorer 設定との照合:**

| 項目 | 現状 | note 現実 | 評価 |
|---|---|---|---|
| word_count B 閾値 | 1900 (今日緩和) | 2,000-5,000 が目安、4,000超で離脱 | **やや緩いが筋は OK** |
| word_count A 閾値 | 4000-5500 | 2,000-5,000、密度のほうが効く | **target が高すぎ。離脱リスク帯** |
| visual_count B 閾値 | 1 (今日緩和) | H2 ごとに画像 1 枚 (H2 が 3 なら画像 3) | **連動してない、過小** |
| heading_structure | H2 ≥ 2 | H2 ≥ 3 が密度ライン | **緩い** |
| title 字数 | 35-70字 | 21-25字帯がトップクリック | **長すぎ。検索枠で切れる** |
| title 要素 | ブラケット + 数字 | ブラケット + 数字 + 状態指名/権威 (3要素必須) | **1 要素不足** |

## 3. AI 検知問題 — 私たちの prompt 自身が AI 生成を疑わせる

note 公式は **2024 年に AI 量産 約19万ページの検索インデックス削減** を実施
([blog-auto-ai](https://blog-auto-ai.jp/article-032.html))。

AI 検知の主な特徴:
- **接続詞濫用**: 「そのため」「つまり」「一方で」「まず」「次に」
- **横棒 ── 多用**
- **同一文末連続** (です/ます だけ続く)
- **過剰に整った論理構造**

**現状の Writer prompt はこれらを誘発する書き方を促している:**
- `note_article_prompt` の「論理的に展開」「段階的に説明」要件
- `deep_dive` 構成パターンの「1. なぜ重要 / 2. 基礎知識 / 3. 核心」テンプレ
  (= 過剰に整った論理構造)

**forbidden_phrases にはこれらの AI 検知ワードが入っていない**。

## 4. ソース戦略 — 現状の collection ミックスの問題

現状の note 候補ソース:
| ソース | 件数 | note 主流とのマッチ度 |
|---|---|---|
| RSS 日本語 (mi-mollet等) | 10件 | 弱い (女性ライフスタイル系の二次まとめ) |
| RSS 韓国 (allkpop等) | 0件 (404 多発) | 中 (K-pop は note 売れジャンル) |
| Reddit r/technology 他 | 35件 | 弱い (海外ニュース直訳になる) |
| Hacker News | 0件 (502 多発) | 弱い (zenn 向き) |
| Knowledge topics (Akabane等) | 3件 | 中 (テンプレ過ぎて差別化弱い) |

**致命的:** 副業体験談 / ChatGPT 実体験 / 占い系 / HARM 悩み系 のソースが **一つもない**。
note 売れジャンル top5 のうち 0/5 をカバーしていない。

## 5. 再設計提案 (3 段階)

### 段階 1: 評価ロジックを note 現実に合わせる (~30分、低リスク)

```python
# generators/objective_scorer.py
# word_count
target_min = 2200  # 4000→2200 に下げる (note は長ければ売れるわけではない)
target_max = 4500  # 5500→4500 に下げる (4000+ で離脱)
accept_min = 1700  # 1900→1700 に下げる (Gemma3 floor を受け入れる)
accept_max = 7000  # 9000→7000 (note 上限)

# visual_count: H2 数連動に変更
def _score_visual_count(article):
    h2_count = ...  # 既存の heading 検出を流用
    visual_count = images + mermaid + tables + code_blocks
    # H2 ごとに 1 枚以上が note ¥800 妥当ライン
    required = max(1, h2_count - 1)  # 導入 H2 だけは画像なし許容
    if visual_count >= required:
        grade = "A" if visual_count >= h2_count else "B"
    else:
        grade = "C"

# heading_structure: H2 ≥ 3 (構造密度ライン)
if h2_count < 3:
    fail_reasons.append(...)
```

### 段階 2: AI 検知ワードを forbidden_phrases に追加 (~10分、低リスク)

```yaml
# config/settings.yaml
evidence:
  forbidden_phrases:
    # 既存パターン省略
    # 2026-05-14 追加: AI 生成検知される接続詞濫用
    - "そのため、(?:[^。]{0,40}。.*?){2,}"   # 3回以上連続使用
    - "つまり、(?:[^。]{0,40}。.*?){2,}"
    - "一方で(?:[^。]{0,40}。.*?){2,}"
    - "──.*──.*──"  # 横棒 3 連
    # AI 文末連続: 「です。」「ます。」が 5 回以上連続
    - "(?:です。\\s*[^。]{1,80}){5,}"
```

### 段階 3: Note 専用 Writer prompt + ソース戦略 (~2-3時間、根本対応)

#### 3-A: note_article_prompt を 2 系統に分岐

`config/prompts.yaml` に:

```yaml
# 既存 note_article_prompt は note_article_prompt_explainer にリネーム
# (Reddit/HN/RSS 海外ニュース由来の解説記事用、既存ロジック)

note_article_prompt_experience: |
  # 一次情報体験談ベース。knowledge_topics + ChatGPT実体験 + 副業体験 系列で使用。
  # 構成: HARM フレームの「悩み → 体験 → 失敗 → 学び → 再現方法」
  # 長さ: 2,200-4,000 字
  # トーン: 一人称 (私) で書く。「ぶっちゃけ」「正直」「失敗した」を強要
  # 例: 「Claude Code に月 $20 払って失敗した話 — 学べた 3 つの教訓」
```

#### 3-B: Source 分岐ロジック

`main.py` の Writer 選択ロジック:
```python
def _select_prompt_for_source(article):
    source = article.get("source", "")
    if source.startswith("knowledge_topics"):
        # 副業 / K-beauty / 自己啓発 系は experience prompt
        return prompts["note_article_prompt_experience"]
    elif source in ("reddit", "hacker_news", "arxiv"):
        # 海外ニュース系は zenn に振る、note には来ないようにする
        return None  # skip
    else:
        # 日本語 RSS (mi-mollet等) は explainer
        return prompts["note_article_prompt_explainer"]
```

#### 3-C: 体験談ソース層の追加

新規 collector `experience_seed_collector.py`:
- `data/experience_seeds.json` (committed, gitignore 除外)
- 自前 telemetry (今日 generate 何回 / Gemma3 コスト / 失敗パターン) を Researcher で
  挿入できる枠を用意
- 体験談テンプレ ("AI 副業を 1 ヶ月やってみた" 等) を knowledge_topics と同等の
  重みで sample

### 段階 4: タイトル 3 要素バリデータ (~30分)

`generators/title_fulfillment_scorer.py` の subjective 評価:
- ブラケット【】の有無
- 数字 (実数) の有無
- 状態指名 ("〜したい人へ" / "アクセス伸びない") or 権威 ("プロが教える" / "誰も教えない") の有無
- **2/3 以上揃わなければ C 自動却下**

タイトル文字数チェック:
- 21-25 字帯にあれば +1 ボーナス
- 40字超は -1 ペナルティ

## 6. 優先順位の提案

| 段階 | 工数 | リスク | 期待効果 |
|---|---|---|---|
| 段階 1 (評価緩和) | 30分 | 低 | 既存出力の合格率改善 (note 1-2件 / run) |
| 段階 2 (AI 検知 deny) | 10分 | 低 | publish 時の note 公式ペナルティ回避 |
| 段階 3 (専用 prompt + ソース分岐) | 2-3時間 | 中 | 根本解決 — note 主流ジャンル対応 |
| 段階 4 (タイトル 3要素) | 30分 | 低 | クリック率改善 |

**推奨フロー:**
1. **今日 / 明日**: 段階 1 + 段階 2 を commit して再 generate → 数本 publish 出る見込み
2. **今週中**: 段階 3 の専用 prompt + ソース分岐
3. **来週**: 段階 4 のタイトル 3 要素バリデータ

## 7. やらないことの整理 (重要)

- **「長くする」方向の調整はもう打ち切る** — Gemma3 12B は 1700-2100 字 が出力中央値。
  ここで戦ってもプロンプト追加では改善しない。長さ閾値を現実に合わせる方が ROI 高い。
- **Reddit / HN ニュースを note 用に翻訳する path は段階的に廃止** — zenn 専用にする。
  note は一次情報・体験談プラットフォーム。
- **「タイトル負け」の根本治療はタイトル生成側** で。本文補強で title_fulfillment を
  満たすのは Writer 性能的に困難。

## 参考リンク

- [note株式会社: 30万件分析](https://note.jp/n/n8522197d1ced?gs=b4464d7e1037)
- [sungrove: note有料記事](https://www.sungrove.co.jp/note-paid-article/)
- [noteup_iinkai: 売れ筋ジャンル2025](https://note.com/noteup_iinkai/n/nfe90356c527a)
- [dapper_poppy7392: 2026年売れるジャンル30](https://note.com/dapper_poppy7392/n/n9de0a55ddc68)
- [yakiimo11: クリックされるタイトル20個分析](https://note.com/yakiimo11/n/n2ac024aecba4)
- [blog-auto-ai: note AI記事 うざい](https://blog-auto-ai.jp/article-032.html)
- [hoboai: ChatGPT記事の見抜き方](https://note.com/hoboai/n/n015a22a0c9e0)
- [yukemuri-blog: 最適文字数15ポイント](https://www.yukemuri-blog.com/note-paid-article-word-2/)
