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
| 4 | 2026-07-13 | ループエンジニアリング scrap (71addcdd3a0ecd) | 「## ## 参考文献」二重ハッシュ体裁バグ + 造語の過剰一般化傾向 | ✅ 二重ハッシュは対策済+7-15 live検証で解消確認。造語一般化は継続観測 |
| 5 | 2026-07-13 | パイプライン | 切断検知時の自動再生成 (regen 連携)。現状は「刈って完結形 or 棄却」まで — 棄却時にトピックが翌日再挑戦される保証はある (Sheets 承認残置) が、明示的な regen ループは無い | 🟡 open |
| 6 | 2026-07-13 | RAG 運用 | ops_incidents.md 更新後の build_rag_index.py 再ingest が人間の規律頼み | ✅ 対策済 `a2b047d` (generate 起動時に mtime 比較で [rag-staleness] WARNING) |
| 7 | 2026-07-13 | STATE.md | 「60行未満で維持」ルールに対し 800行超に肥大。古い In Flight を archive へ機械的に押し出す仕組みが必要 (process audit e) | 🟡 open |
| 8 | 2026-07-14 | note全4本 | 本文H1が公開タイトルに昇格し stored title と乖離、¥500有料で「【完全無料】」露出 (→ ops#24) | ✅ 対応済 (H1採用全ソース化+価格矛盾ゲート+live修正、7-14) |
| 9 | 2026-07-14 | note全4本 | url_cleaner の URL剥離で「出典: ROOMIE —」ダングリング多発 (→ ops#25) | ✅ 対応済 (_BARE_URL_RE 非ASCII除外+修復パス+live修正、7-14) |
| 10 | 2026-07-14 | note記事3-4 (¥500×2) | 有料の情報密度不足 (ROOMIE 1本の敷衍) + アフィリ不整合 + 記事4は :::message 生表示疑い/画像0。user 判断=タイトル修正のみ (¥500維持) → 実施済。情報密度の構造課題は残 | 🟡 open (密度のみ) |
| 11 | 2026-07-14 | Cursor scrap (10de0daec2c410) | 破壊的コマンド検出regexが rm -rf を検出できずコア主張を裏切る (E1) | 🟡 open |
| — | 2026-07-14 | backlog #1 画像テーマゲート | **悪化**: note3本で被写体完全不一致 (人魚/マイク/楽譜)。クエリ汚染は対策済 (コードフェンス/出典行除去+媒体名blacklist、7-14)。被写体語彙ゲート自体の強化は継続課題 | 🟡 open (縮小) |
| 12 | 2026-07-15 | publish パイプライン | 修正デプロイ前に生成された承認済み記事 (carryover) が publish 時に再サニタイズされず、旧欠陥が live 再流出 (→ops#26) | ✅ 対応済 (publish時 re-sanitize パス + live 4本修正、7-15) |
| 13 | 2026-07-15 | is_incomplete ゲート | 2盲点: (a)リスト項目内切断 → ✅対応済 (40字+の無終端リスト項目を検知、7-15)。(b)約束セクション欠落 → 🟡 open 継続 (ヒューリスティック設計要) |
| 14 | 2026-07-15 | title_fulfillment | 「専門家」「氷点下」「データが示す」等の名詞レベル約束 → ✅ 対応済 (_title_claims_unfulfilled を生成+publish 2層配線、7-15)。live 猛暑対策はタイトル修正済 |
| 15 | 2026-07-15 | knowledge_topic 有料 | #22 の citation exempt の副作用: evidence_required 実URL 0 でも有料化可能 | ✅ 対応済 (実URL引用ゼロ×price>0 は ¥0 強制、7-15)。有料の情報密度自体は #10 で継続 |
| 16 | 2026-07-15 | LLM 偽アンカーリンク | `[オルビス公式…](# オルビス…)` 型の # プレースホルダURL+架空オファー (初回¥1,000等) を本文に捏造 (エクソソーム/K-beauty記事で live 流出) | ✅ 根本対応済 (7-16): 真犯人は LLM でなく .env の #placeholder アフィリ値を _is_valid_link が通していた → http(s) 以外を全却下。sanitizer line-kill は第2層として維持 |
| — | 2026-07-14 | backlog #3/#4 zenn体裁 | **再発・悪化**: `## ##` が5箇所 (前回1)、擬似コード未定義参照、取得日が2024固定の年ずれ | 🟡 open 継続 |
| 17 | 2026-07-16 | K-beauty (n9245a67de5ee) | #16 偽アンカー再発: `](# …)`+捏造オファー(オルビス初回¥1,000/30日返品保証, DHC, BLOOMBOX)が **affiliate footer** で live 流出。line-kill は editorial のみ走り affiliate は re-sanitize 対象外 | 🟡 open |
| 18 | 2026-07-16 | ハーブLED (n44cd8cbafd9f) | ops#22 亜種: `知識-topic://gd_001` が live 流出。sanitizer/deny の `knowledge[-_]topic://` が LLM 日本語化 (知識) を素通し | 🟡 open |
| 19 | 2026-07-16 | 給餌器/ハーブ (nc778/n44c) | 約束セクション欠落 (backlog#13b): 記事3=「3日間ガイド」Day1のみで Day2/3欠落、記事4=まとめ欠落。両方 live 切断。is_incomplete は末尾完結文のため未検知 | 🟡 open (13b継続・実害2件) |
| 20 | 2026-07-16 | 給餌器 (nc778e...) | 画像被写体不一致 (backlog#1 悪化): 猫給餌器記事に映画撮影スタジオ/緑衣装女性 stock 4枚全て無関係。pet_life 新カテゴリのクエリ汚染 | 🟡 open (#1 悪化) |
| 21 | 2026-07-16 | zenn scrap 2本 (2c05/6988) | 画像 markdown 破損 `](data/images/stock/…jpg ")` (stray quote + local path、zenn未解決) + 両本が同一の汎用ノートPC写真 (被写体無関係) | 🟡 open |
| 22 | 2026-07-16 | knowledge_topic note 3本 | 具体価格・型番 (¥19,800/¥18,150/P570/P571) を出典ゼロで断定。¥0降格は発火(良)だが読者は無典拠の数値を受領。IKEA VÄXER は実世界で製造終了疑い | 🟡 open (#10密度と連結) |
| 23 | 2026-07-16 | ハーブLED (n44c) | 中国語混入 `模块化` が live 流出 (モジュール化の誤変換)。K系分離ルールと別の言語汚染 | 🟡 open |
