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
| 2 | 2026-07-13 | 割れないグラス (n62fa415c97a8) | 「## ⚠️ 免責事項」が空見出しのまま残留 | ✅ 系統対策済 `a2b047d` (sanitizer が空免責見出しを除去)。live 側の既公開1件は cosmetic のため未修正 (feedback_no_exhaustive_cleanup 準拠) |
| 3 | 2026-07-13 | CAD設計論 scrap (a97d79a71be870) | 擬似 React コードで useEffect 内の wsConnection を外スコープから参照 (未定義参照)。「擬似コード」と開示済みのため低優先 | 🟡 open |
| 4 | 2026-07-13 | ループエンジニアリング scrap (71addcdd3a0ecd) | 「## ## 参考文献」二重ハッシュ体裁バグ + 造語の過剰一般化傾向 | 🟡 open |
| 5 | 2026-07-13 | パイプライン | 切断検知時の自動再生成 (regen 連携)。現状は「刈って完結形 or 棄却」まで — 棄却時にトピックが翌日再挑戦される保証はある (Sheets 承認残置) が、明示的な regen ループは無い | 🟡 open |
| 6 | 2026-07-13 | RAG 運用 | ops_incidents.md 更新後の build_rag_index.py 再ingest が人間の規律頼み | ✅ 対策済 `a2b047d` (generate 起動時に mtime 比較で [rag-staleness] WARNING) |
| 7 | 2026-07-13 | STATE.md | 「60行未満で維持」ルールに対し 800行超に肥大。古い In Flight を archive へ機械的に押し出す仕組みが必要 (process audit e) | 🟡 open |
| 8 | 2026-07-14 | note全4本 | 本文H1が公開タイトルに昇格し stored title と乖離、¥500有料で「【完全無料】」露出 (ops#21 の残存構造ギャップが実害化 → ops#24 に昇格) | 🔴 要対応 |
| 9 | 2026-07-14 | note全4本 | url_cleaner の URL剥離で「出典: ROOMIE —」ダングリング多発 (ops#22亜種 → ops#25 に昇格、ローカルJSONで9箇所実証) | 🔴 要対応 |
| 10 | 2026-07-14 | note記事3-4 (¥500×2) | 有料の情報密度不足 (ROOMIE 1本の敷衍) + アフィリ不整合 + 記事4は :::message 生表示疑い/画像0。タイトル修正 or ¥0降格をユーザーに提案中 | 🔴 ユーザー判断待ち |
| 11 | 2026-07-14 | Cursor scrap (10de0daec2c410) | 破壊的コマンド検出regexが rm -rf を検出できずコア主張を裏切る (E1) | 🟡 open |
| — | 2026-07-14 | backlog #1 画像テーマゲート | **悪化**: note3本で被写体完全不一致 (人魚/マイク/楽譜)。クエリに source名(ROOMIE)/本文偶発トークン(mermaid/Dolby)が混入する生成崩壊 | 🔴 要対応 (#1を昇格) |
| — | 2026-07-14 | backlog #3/#4 zenn体裁 | **再発・悪化**: `## ##` が5箇所 (前回1)、擬似コード未定義参照、取得日が2024固定の年ずれ | 🟡 open 継続 |
