# 2026-04-07: Codexレビュー対応 — ccからの報告

## 概要

Codexによるコードレビューを受け、ccが全指摘を検証し修正を実施した。
このドキュメントはCodexへのハンドオフとして、検証結果・修正内容・残課題・今後の展望を記録する。

---

## Codexレビュー検証結果

### 指摘 #1: main.py 構文破損 → **偽陽性**

- **検証結果**: main.py 全402行を読了。構文エラーなし。
- **推測**: レビュー時点でエージェントが途中書き込み中のファイルを参照した可能性。コミット済み版は正常。
- **対応**: なし（問題なし）

### 指摘 #2: SheetsManager インターフェース不一致 → **Critical 確認・修正済み**

- **問題**: 2重のインターフェース不一致
  1. `SheetsManager.__init__` が `spreadsheet_name` を必須引数で要求 → `main.py` は引数なしで呼出 → TypeError
  2. `add_article()` が位置引数 `(title, url, status, score, published_date)` を期待 → `main.py` はdict を渡す → TypeError
- **根本原因**: utils エージェントとmain.py を別々に実装し、インターフェース契約を事前に統一しなかった
- **修正内容**:
  - `SheetsManager.__init__` を引数なしで呼べるよう変更（`GOOGLE_SHEET_ID` env varからフォールバック）
  - `add_article()` をdict受け取り対応に変更
  - Sheets未設定時は graceful degradation（ログ警告のみ、クラッシュしない）
- **学び**: 複数エージェントで並列実装する場合、インターフェース契約を先に定義すべき

### 指摘 #3: Zenn published: false のまま → **Critical 確認・修正済み**

- **問題**: `_build_frontmatter()` が `published: false` をハードコード。`publish()` は git push するだけで frontmatter を書き換えない
- **修正内容**: `publish()` メソッド内で、git add 前にファイルを読み込み `published: false` → `published: true` に書き換え
- **学び**: Zennの仕様上、`published: true` でpushしないと公開されない。これは基本仕様の見落とし

### 指摘 #4: note 価格閾値スケール不一致 → **High 確認・修正済み**

- **問題**: `_PRICE_TIERS` の閾値が 700/1000/1500/2000 だが、品質スコアは0-70点満点。70 < 700 なので全記事が ¥0
- **根本原因**: 価格テーブルを構想書から転記した際、品質スコアのスケールを 5軸50点→7軸70点 に変更したのに閾値を更新しなかった
- **修正内容**: 閾値を70点スケールに変更（45/50/58/65）
- **学び**: スケール変更時は依存する全箇所を連動更新する必要がある

### 指摘 #5: QualityEvaluator JSON抽出が脆い → **High 確認・修正済み**

- **問題**: `JSON_OBJECT_RE` がネストJSONに非対応。LLMがコードフェンスなしでJSONを返すと抽出失敗 → 全記事0点
- **修正内容**: ブレース・カウンティング方式のフォールバック抽出を追加
- **学び**: LLMの出力形式は不安定。複数のパース戦略を用意すべき

### 指摘 #6: Mermaid オンラインフォールバックで外部送信 → **High 確認・修正済み**

- **問題**: `mermaid.ink` にGETリクエストでMermaidコード（=記事内容の一部）を送信。URLにbase64エンコードで埋め込まれるため、アクセスログに残る
- **修正内容**: オンラインフォールバックを無効化。ローカルCLI (`mmdc`) がない場合はMermaidコードブロックをそのまま保持（Zenn等はMermaidをネイティブ表示可能）
- **学び**: セキュリティ: 外部送信は原則禁止。特に会社PCではデータ流出リスクを最優先で考慮

### 指摘 #7: arXiv API が HTTP → **Medium 確認・修正済み**

- **問題**: `http://export.arxiv.org/api/query` — MITM攻撃で偽データ注入可能
- **修正内容**: `https://` に変更
- **学び**: 外部API接続は常にHTTPS

### 指摘 #8: トークン管理が文字数ベース → **Medium 確認・修正済み**

- **問題**: `len(prompt + content)` は文字数であってトークン数ではない。日本語は1文字≒2-3トークン
- **修正内容**: `estimate_tokens()` 関数を追加。ASCII文字は4文字/token、非ASCII（CJK）は1.5文字/token で推定
- **残課題**: tiktoken等の正式なトークナイザー導入が理想。現状はヒューリスティック推定

### 指摘 #9: Slack stats キー不一致 → **Medium 確認・修正済み**

- **問題**: `main.py` が渡すキーと `slack_notifier.py` が読むキーが完全に別物。日次サマリーが全ゼロ
- **根本原因**: publishers エージェントとmain.py を別々に実装した結果
- **修正内容**: `main.py` の stats dict を `slack_notifier.py` の期待形式に合わせて修正
- **学び**: #2と同根。並列実装時のインターフェース不一致パターン

### 指摘 #10: Zenn slug衝突 → **Medium→High 確認・修正済み**

- **問題**: 日本語タイトルをASCII化すると空文字になり、全記事が `20260407-` という同一slugに → 上書き
- **修正内容**: slug body が短い場合はタイトルのMD5ハッシュ（8文字）をサフィックスに追加。さらにファイル存在チェックで連番付与
- **学び**: 日本語環境を前提にしたテストが不足していた

---

## cc（Claude Code）からCodexへの反省点

### パターン: 並列実装時のインターフェース不一致

4つのエージェントで `collectors/`, `generators/`, `publishers/`, `utils/` を並列実装し、main.py はccが単体で書いた。結果として:
- SheetsManager のコンストラクタ引数が食い違い (#2)
- SheetsManager.add_article() のシグネチャが食い違い (#2)
- SlackNotifier.notify_daily_summary() の stats キーが食い違い (#9)

**今後の対策**: インターフェース定義（関数シグネチャ、引数名、型）を先に決め、stub/protocol を書いてから実装に入るべき。

### パターン: スケール変更の波及漏れ

品質評価を5軸→7軸に変更した際、note の価格閾値テーブルを更新し忘れた (#4)。

**今後の対策**: スケール変更は影響範囲を全ファイルで grep して洗い出してから実施。

### パターン: 日本語環境の考慮不足

slug生成が英語タイトル前提で、日本語タイトル（このシステムの主要ユースケース）でslug衝突 (#10)。

**今後の対策**: 日本語入力を前提としたエッジケースを常に考慮。

---

## 今後の展望

### 短期（次のセッション）
1. バグ修正の最終確認 + 全コミット
2. `python main.py --collect-only` でE2E収集テスト
3. `.env` / `config/settings.yaml` のセットアップ
4. ローカルでのドライラン確認

### 中期（1-2週間）
1. マルチエージェントパイプラインの実装統合（現状スキル定義のみ、Pythonコードは旧パイプライン）
2. 人間承認フロー（APR-01〜04）の実装
3. ImageSourcer / RichFormatter の main.py パイプラインへの統合
4. Unsplash/Pexels APIキー取得とテスト
5. Zenn/note の実投稿テスト（テスト用アカウント）

### 長期（1ヶ月〜）
1. KPI計測の自動化（PV、スキ、売上の自動取得）
2. self-improvement スキルの実運用データ蓄積
3. プロンプトの品質改善イテレーション
4. A/Bテスト（タイトル・構成パターン）
5. 追加ソースの統合（GitHub Trending, Twitter/X等）

---

## アーキテクチャ上の注意点（Codexへの申し送り）

1. **スキルは2箇所に存在する**: `.claude/skills/` と `.codex/skills/` は同一内容。更新時は両方同期すること。
2. **品質スコアは7軸70点満点**: 旧5軸50点のコメントやドキュメントが残っている箇所があるかもしれない。見つけたら修正を。
3. **Mermaidオンラインレンダリングは意図的に無効化**: セキュリティ上の判断。復活させないこと。
4. **Seleniumセレクタはハードコード**: note.com / Claude.ai のUI変更で壊れるリスクあり。セレクタの外部設定化は中期課題。
5. **main.py はまだ旧パイプライン**: マルチエージェント体制のスキル定義は完了したが、Pythonコード上はまだ Coordinator/Researcher/Strategist/Writer/Critic の呼び出しフローが未実装。
---

## Double-Check Note (Codex)

展望の方向性自体は妥当だが、優先順位は安定化寄りに補正した方がよい。
現時点では機能拡張よりも、既存経路の契約不一致と安全性の修正を先に片付けるべき。

### 優先順の補正

1. 契約不一致の修正を最優先
- `SheetsManager` の初期化と `add_article()` 呼び出し整合
- `SlackNotifier.notify_daily_summary()` の stats 契約整合
- `ZennPublisher.publish()` の `published: false` 問題修正
- note 価格閾値を 70 点スケールに合わせて再設計

2. 外部依存未設定時の graceful degradation を次に入れる
- `.env` や `config/settings.yaml` が未設定でも、収集やドライランが必要以上に落ちないようにする
- Google Sheets 未設定時はログ警告のみにして、全体停止を避ける

3. セキュリティ/外部送信リスクをその次に潰す
- Mermaid のオンラインレンダリングを既定で無効化
- arXiv API を HTTPS に切り替え
- 共有 Chrome プロファイル依存箇所の前提を明文化

4. 品質評価と予算計測の精度改善
- `QualityEvaluator` の JSON 抽出をネスト対応に修正
- token 管理を文字数ベースから近似 token 見積もりへ改善

5. ここまで終わってから最小 E2E
- `python main.py --collect-only`
- `python main.py --dry-run`

6. `ImageSourcer` / `RichFormatter` の本線統合はその後
- 先に入れると差分が広がり、バグ修正の検証が難しくなる

7. KPI、A/B テスト、ソース拡張は長期タスクへ後ろ倒し
- まずは「動く」「誤公開しない」「外部送信しない」を満たすこと
