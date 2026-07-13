# Review Backlog — article-reviewer の未対応指摘トラッカー

article-reviewer subagent が出した 🟡/NOTE 級の指摘のうち、即時対応
しなかったものをここに追記して追跡する (🔴 は即対応 or ops_incidents 行き)。
RSI process audit (2026-07-13) の指摘 b: 「トリアージから漏れた指摘が
会話ログと共に蒸発する」への対策。

**運用**: article-reviewer は各レビューの最後にこのファイルを読み、
open 項目が新レビューで再確認されたか (解消/継続/悪化) を報告する。
対応したら status を ✅ に変え、対応 commit を書く。

| # | 日付 | 記事/対象 | 指摘 | status |
|---|------|-----------|------|--------|
| 1 | 2026-07-13 | 割れないグラス (n62fa415c97a8) | stock 画像 4 枚全てが撮影スタジオ/ネオン等でグラスと無関係 (G4)。lifestyle 系の画像クエリ/テーマ整合ゲートが弱い | 🟡 open |
| 2 | 2026-07-13 | 割れないグラス (n62fa415c97a8) | 「## ⚠️ 免責事項」が空見出しのまま残留 (live 修正は未実施、軽微) | 🟡 open |
| 3 | 2026-07-13 | CAD設計論 scrap (a97d79a71be870) | 擬似 React コードで useEffect 内の wsConnection を外スコープから参照 (未定義参照)。「擬似コード」と開示済みのため低優先 | 🟡 open |
| 4 | 2026-07-13 | ループエンジニアリング scrap (71addcdd3a0ecd) | 「## ## 参考文献」二重ハッシュ体裁バグ + 造語の過剰一般化傾向 | 🟡 open |
| 5 | 2026-07-13 | パイプライン | 切断検知時の自動再生成 (regen 連携)。現状は「刈って完結形 or 棄却」まで — 棄却時にトピックが翌日再挑戦される保証はある (Sheets 承認残置) が、明示的な regen ループは無い | 🟡 open |
| 6 | 2026-07-13 | RAG 運用 | ops_incidents.md 更新後の build_rag_index.py 再ingest が人間の規律頼み。mtime と index sentinel の突き合わせ警告を generate 冒頭に足す案 (process audit e) | 🟡 open |
| 7 | 2026-07-13 | STATE.md | 「60行未満で維持」ルールに対し 800行超に肥大。古い In Flight を archive へ機械的に押し出す仕組みが必要 (process audit e) | 🟡 open |
