# RAG 構築 要件定義 (2026-05-11)

ベクトル DB / RAG 構成への移植について、2026-05-11 のセッションで
合意した方針を凍結する。Sprint 2 以降の実装はこの要件に従う。

## 1. 目的とゴール

ユーザー（オペレーター本人）の優先順位を反映：

1. **最優先: 嘘をつかないこと** = ハルシネーション 0 化
2. **次点: 質** = 深さ、独自性、説得力
3. **量は数えない** = 「N 本 / 日」のような volume KPI は設けない
4. **基本イメージ: 動き続ける運用** = 手動トリガーを頻繁に回す
   - スケジューラ自動起動は行わない (memory: `feedback_no_scheduler.md`)
5. **モデルは実証で選定** = ベンチマーク + 本プロジェクト固有の eval set で決める

## 2. 評価指標

### 主指標
- **ハルシ deny ヒット率** = 公開後にハルシ事故レジストリに追加された件数 / 週
  - ベースライン: 直近 4 週で 1-2 件/週
  - ゴール: 0.3 件以下/週 (5-7 倍改善)

### 副指標
- **主観 grade A 率** = critic + scorer 評価で grade A になった割合
- **客観 grade A 率** = objective_scorer の集約 grade
- **重複類似度** = 既存 247 記事との semantic 類似度の最大値
  - ゴール: 0.85 以上が出ない

### 計測しないもの
- 「N 本/日」「総 publish 数」等の volume 指標

## 3. スプリント順序 (再優先付け)

```
Sprint 1 (完了): infra (retriever + index builder + 3 collections)

Sprint 2 (次): ハルシ 0 化のための Critic 強化
  - 既存 critic の forbidden_phrases regex check に
    hallucinations collection への semantic retrieval を追加
  - 類似度 0.65+ の過去事故が見つかったら LLM に検証問いかけ
  - 「ありそう」と判定 → 自動却下 or 修正指示

Sprint 3: 重複検出
  - past_articles collection (新規) に title + summary を embed
  - 新トピック投入時に類似度 0.85+ をチェック
  - 警告 (自動却下はしない、angle 提案にとどめる)

Sprint 4: prompt 配線 (旧 Sprint 2)
  - _generate_single_article の learned_block を retrieval ベースに
  - env RAG_ENABLED で gating、デフォルト OFF
  - A/B 評価で grade A 率を計測

Sprint 5: 画像 alt 妥当性 (semantic gate)
  - 既存の語彙ベースゲートを semantic 類似度ベースに置換
  - 記事本文 vs 画像 alt の cos sim < 0.4 で reject
```

## 4. 埋め込みモデル選定 (Sprint 2 着手前に決定)

### 候補
| モデル | サイズ | 特徴 |
|---|---|---|
| multilingual-e5-base (現採用) | 278M | バランス、ベースライン |
| multilingual-e5-large | 560M | 精度最強級、重い |
| BGE-M3 | 568M | hybrid (dense + sparse + multi-vec) 対応 |
| Ruri (cl-nagoya/ruri-large) | 337M | 日本語ベンチ1位、未検証だが強力候補 |
| sup-simcse-ja-base | 110M | 軽量、補欠 |

### 検証手順
1. **金の正解セット作成** (20-30 ペア)
   - クエリ → 期待 chunk のペア
   - 例: 「伏字 店名」→「## 4. 〇〇/×× 等 未置換伏字」
2. **各モデルで Recall@5 / MRR を計測**
3. **速度 + メモリも合わせて測定**
4. **このプロジェクトでの最適モデルを決定**
   - 成果物: `docs/knowledge/rag_model_selection_2026-05-11.md`
   - どのモデルを何の理由で選んだか + 数値根拠

時間見積: 3-4 時間 (eval set 1h + 4 モデル測定 2h + 結論 30 分)

## 5. 受け入れ基準

### Sprint 2 (ハルシ critic) 完了条件
- [ ] テスト記事 (過去ハルシ事故を含む 10 件) で critic が事故を 90%+ 検出
- [ ] 既存 forbidden_phrases regex を破壊しない (40 deny + 7 sanitizer の test 維持)
- [ ] critic 実行時間が 既存 +30% 以下

### Sprint 3 (重複検出) 完了条件
- [ ] 既存 247 記事のうち、相互類似度 0.85+ ペアを正しく検出
- [ ] 偽陽性率 (本来別記事と判定すべきが類似と誤検出) 10% 以下

### Sprint 4 (prompt 配線) 完了条件
- [ ] env RAG_ENABLED=false で動作完全不変 (既存パイプライン保証)
- [ ] env RAG_ENABLED=true で A/B 7日 × 5記事 のサンプルで grade A 率が baseline 比 +10% 以上 (有意水準 0.10)
- [ ] retrieval ヒットが 0 件のとき gracefully fallback (静的 stuffing に戻る)

## 6. ロールバック条件

以下のいずれかが発生したら RAG 機能を flag off に戻し、原因調査：

- 公開記事に新規ハルシネーション事故 (registry へ追加レベル)
- 客観 grade A 率が baseline 比で下降
- 生成時間が baseline 比 +50% 以上増加
- chromadb / embedding model が import エラー連発

## 7. 運用ルール

### 知識更新時の流れ
1. `docs/knowledge/quality_*.md` または `hallucination_registry.md` を編集
2. `py scripts/build_rag_index.py` で再ビルド (~5秒)
3. `--test` フラグで 4-5 件のサンプルクエリ確認

### `--learn` との連動 (Sprint 2 で実装)
- `--learn` 末尾に `subprocess.run([sys.executable, "scripts/build_rag_index.py"])` を追加
- env `RAG_AUTO_REINDEX=false` で無効化可能 (デフォルト true)

### インデックス破損時
- `data/rag_index/` を rm して再ビルドで復旧 (5 秒程度)
- データ損失なし (md ファイルが正典)

## 8. 開いている疑問点

| # | 質問 | 暫定方針 |
|---|---|---|
| 1 | 既存 `_load_learned_block` と RAG retrieval を **置換** か **併用** か？ | Sprint 4 で A/B 検証する。デフォルトは併用 (フェイルオープン) |
| 2 | Critic に retrieval 結果を渡す際の LLM 問いかけ文の最適化 | Sprint 2 実装中に経験的に詰める |
| 3 | engagement-aware retrieval (performance.jsonl との結合) は要るか？ | Sprint 4 完了後に判断 |
| 4 | Cross-encoder reranker を追加するか？ | 22 chunks 規模では不要、500+ chunks で検討 |
| 5 | fine-tuning (LoRA 等) は要るか？ | 80 doc 規模では過剰、要不要は 1000+ doc になってから |

## 9. 関連ドキュメント

- `memory/project_rag_migration.md` — point-in-time 観測
- `generators/rag_retriever.py` — Sprint 1 実装
- `scripts/build_rag_index.py` — Sprint 1 builder
- `docs/knowledge/hallucination_registry.md` — Sprint 2 で retrieval 対象になる正典

---

更新履歴:
- 2026-05-11 初版 (Sprint 1 完了 + 優先度再合意)
