# Output Capabilities

このツールでどのような成果物が生成できるかを、**実際に 2026-04 で公開された実データ**を交えて整理したドキュメントです。

## 対象プラットフォーム

| プラットフォーム | 認証 | 投稿経路 | 主なコンテンツ軸 |
|---|---|---|---|
| Zenn | GitHub 連携（`ZENN_REPO_PATH`） | git push → 自動ビルド | 技術記事、論文解説、AIツール実務 |
| note | Playwright による Web UI 自動化 | エディタ操作 | トレンド、韓国、美容、ライフスタイル、マネタイズ |

## 生成フロー

```
--generate:
  arXiv + RSS(日本語/韓国/グルメ/コーヒー) + Reddit + Google Trends
    → トレンドスコア計算・ランク付け
    → 構成パターン自動選択 (standard / listicle / trend_report / howto / tutorial / deep_dive …)
    → learned block 注入 (直近の人気タイトル / フレーズ / タグ分布)
    → ローカル LLM (Gemma3) で記事生成
    → 客観スコアリング (ObjectiveScorer: 引用数 / Tier1-2 比率 / 視覚要素 / チェーン店検出 / 文字数)
    → 主観スコアリング (SubjectiveEvaluator: 独自性 / 正確性 / 可読性 / 引き込み / タイトル-本文一致)
    → 集約判定 (ScoreAggregator A/B/C。C は自動却下)
    → 閾値未達なら一度だけ自動再生成 (文字数不足 or 総合 B の 75-87.5 帯)
    → トピカル Unsplash カバー画像生成
    → ArticleStore に保存 (data/articles/*.json)
    → Sheets に「⏳承認待ち」で登録
    → Gmail + Slack 通知

--publish:
  Sheets から「✅承認」のみ取得
    → ArticleStore からコンテンツ読み込み
    → ハッシュタグ自動生成 (キーワードマップ × 学習データブレンド)
    → Zenn: /images/<slug>/ に画像コピー → git commit → push
    → note: Playwright → タイトル/本文 HTML 貼り付け → H2 ごとに画像分散アップロード → figcaption
    → Slack / Gmail 通知

--learn:
  note 人気記事をスクレイピング (5 + 9 カテゴリ、計 280 件)
    → タイトル / 構造 / タグ分布 / 有料記事比率の抽出
    → docs/knowledge/note-trends/YYYY-MM-DD_auto_learning.md に保存
    → 次回 --generate 時に自動注入
```

## 成果物タイプ

### 1. 技術解説 (Zenn 向け)

arXiv プレプリント・公式ドキュメント・技術ブログから題材を取り、3500〜4500 字で以下の構造で出力します。

- 論文の背景 → 研究の発明点 → 実装詳細 → 実務への示唆
- H2 5〜7 個、`mermaid` フロー図、引用ブロック最低 3 箇所、参考文献付き
- タイトルは `【完全ガイド】` `【永久保存版】` 等のブラケット攻め + 技術固有名詞

**実例** (2026-04-20 公開):
- 「【完全攻略】強化学習 PPO で AtCoder Candy Box に挑む — 育児とエンジニアリングの狭間から」 (4,330 字 / A 評価)
- 「【衝撃】Vercel April 2026 インシデント — 内部システムへの不正アクセスから読み解く、現代のクラウドセキュリティの脆弱性」
- 「【警告】AI プロンプトの再現性問題は、自動チューニングで解決できるのか？」

### 2. 一般向けトレンド記事 (note 向け)

note v3 検索 API + Google Trends から題材を取り、5000 字前後・H2 6〜8 個・画像 4 枚を各 H2 に分散配置した構成で出力します。

**実例** (2026-04-21 公開、すべて一次ソース確認済み):
- 「【完全保存版】2026 年春、韓国コスメ "次くる" 8 選 — Hani 愛用の定番から NAD セラムまで」 (5,409 字)
  - ソース: 美的.com / VOCE / Funliday / Cosmetics Business (K-beauty trends 2026)
- 「【完全保存版】2026 年春 K-POP 覇権マップ — BTS 復帰、BLACKPINK 新作、BABYMONSTER 躍進が同時に起きる年」 (5,314 字)
  - ソース: Kpop Profiles / Korea Times / Korea Herald
- 「【そもそも解説】ダーマペン × エクソソーム — 2026 年女性美容医療の主役施術を冷静に見る」 (約 6,500 字)
  - ソース: 美容皮膚科複数院公式 / PMDA ガイドライン

### 3. 事実訂正記事 (note 向け、retroactive)

ローカル LLM の生成過程でハルシネーション（架空店名・架空アカウント・捏造統計）が含まれてしまった公開済み投稿を、**一次ソース確認した事実ベース**に書き換える経路。

**実例** (2026-04-20 適用、`data/rewrites/` に記録):
- 「習近平が Bluesky 投稿」架空分析 → 「中国指導部の SNS / メディア戦略解説」(新華社 / 人民日報 / CGTN を引用)
- 「妻夫木聡の Bluesky 投稿」未確認前提 → 「日本俳優の SNS 活用タイプ分類解説」
- 極秘個室焼肉店「秘肉」(架空店舗) → 「SNS 発グルメ情報の見極め方 5 チェックポイント」
- 「南海電鉄 AI 導入 15% 削減」(捏造統計 + 架空の "Dr. X" 引用) → 「日本鉄道業界の実在 AI 事例解説」
- 「大阪都構想」日付矛盾 → 2015 / 2020 住民投票の実データ + 否決後の政治動向

## 品質保証

### 客観スコア (ObjectiveScorer)

| 指標 | A 基準 | B 基準 | C (不合格) |
|---|---|---|---|
| Tier1-2 ソース比率 | 80%+ | 60%+ | <60% |
| 引用数 | 5 件以上 | 2-4 件 | 0-1 件 |
| 視覚要素 (画像 / 表 / mermaid / code) | 5+ | 2-4 | 0-1 |
| 文字数 | 2500-3500 字 | 1300-4500 字 | それ以外 |
| 禁止フレーズ | 0 件 | - | 1+ 件 |
| チェーン店 | 0 件 | - | 1+ 件 |
| 見出し構造 | H2 5+ 正当 | - | H1 誤用 |

客観 C が一つでもあれば即却下、再生成トリガーにもならない。

### 主観スコア (SubjectiveEvaluator)

LLM に 4 軸 (独自性 / 正確性 / 可読性 / 引き込み) + タイトル-本文一致を評価させ、**各軸に根拠文 (reason) を必須**で出力させる。タイトル-本文一致が C だと総合 C 却下。

### 再生成ループ

- 総合 B で数値スコア 75-87.5 帯 → 1 回再生成
- または 1900 字未満 → 無条件で 1 回再生成
- 再生成時は低評価軸を具体化した `_build_regen_feedback` を注入 (e.g. 「現在 1683 字、最低 2800 字まで +1117 字を [具体例 / 引用 / 数値 / Q&A / 筆者スタンス] で拡張」)

### note 有料化

```
A + A evidence → ¥1,980
A + B evidence → ¥980
B + A evidence → ¥500
B + B evidence → ¥300
その他         → 無料
```

## セーフガード

- **Places API 検証**: note のグルメ / 地域記事では Google Places API で店名実在を確認し、検証失敗した店ブロックは削除。チェーン店は `settings.yaml` のブラックリストで自動除外。
- **`※画像はイメージです` 注記**: note のインライン画像は note 独自の `<figcaption>` に入れることで、note 標準の小さい / 中央揃えスタイルで表示。
- **一次ソース強制**: プロンプトで「架空の URL・発言・店名・統計値を書かない」を明示、Codex ブリーフで事前ファクトグラウンディング。
- **再生成は 1 回限り**: コスト制限を兼ねる + 無限ループ防止。
- **`.env` / 認証情報は .gitignore で保護**: Zenn 用 GitHub トークン、note Cookie、Google Sheets 秘密鍵、OAuth トークンはすべてリポジトリ外。

## 運用コマンド例

```bash
# 収集 → 生成 → スコア → Sheets 登録 (承認待ち)
py main.py --generate

# Sheets で ✅承認 したものだけを公開
py main.py --publish

# 直近 note 投稿を再学習
py main.py --learn

# 公開済み記事のインライン画像を修復
py scripts/fix_recent_note_images.py --count 10

# 架空記事を事実ベースに差し替え
py scripts/apply_rewrites.py --only <note_slug>

# Zenn 公開済み記事の /images/<slug>/ 化 (画像レンダリング修復)
py scripts/fix_zenn_broken_images.py

# ハンドメイド原稿を publish (Sheets バイパス)
py scripts/publish_custom_post.py data/custom_posts/<spec>.json
```

## 実績サマリ (2026-04 時点)

- Zenn 公開: 40+ 記事 (arXiv / AI / Web 技術)
- note 公開: 46 記事 (K-beauty / K-POP / 美容医療 / 東京個人店 / トレンド解説)
- 事実訂正実施: 6 記事 (架空店名 + 架空 SNS アカウント + 捏造統計)
- 学習サンプル: 累計 280 件の人気 note 記事からタグ / タイトル / 構造を抽出
