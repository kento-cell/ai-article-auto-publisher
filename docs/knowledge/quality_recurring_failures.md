# Quality Pattern — 繰り返し観測される不合格・偏りパターン

_記録日: 2026-04-15 (パイプライン1回実行から抽出)_

短く具体的に。再現したら既存項目を更新、別パターンは追記。

---

## 1. arXiv論文 → `citation_format` で構造的に不合格

**観測:** `Pair2Scene: Learning Local Object Relations...` (zenn) →
`citation_format: 0/2 citations have URL (0% < 50%)` で却下。

**原因:** arXiv の abstract には参考文献URLが含まれない。LLMが本文に
引用を入れても URL+日付の充足率が満たせず、論文系記事は構造的に落ちる。

**対処候補:**
- arXiv ソース時は abs URL 自体を引用扱いに昇格
- もしくは zenn × 論文ジャンル時のみ `citation_format` 閾値を緩和
- `generators/objective_scorer.py` の citation_format ロジックを確認

**ステータス:** 未対処。次回arXiv論文を生成する前に修正必須。

---

## 2. Bluesky note枠で同一エリアが連続選択される

**観測:** Sheets ログに `recent: 下北沢,下北沢,下北沢,下北沢,下北沢,下北沢` →
6回連続で「下北沢」エリアの店が選ばれている。地域偏り回避ロジックは
動いている (recent バッファに記録されている) が、**選定段階で除外されていない**。

**原因(推定):** recent バッファを参照しているが、Blueskyソースの店舗エリア
タグが「下北沢」ばかりで代替候補が無い → fallback で結局 下北沢 を選ぶ。
もしくは recent 重複ペナルティが弱い。

**対処候補:**
- Bluesky収集側でエリアタグの多様性を担保（複数キーワードで分散収集）
- recent ペナルティを soft → hard exclusion に変更
- 関連: `main.py` の note Bluesky枠選定ロジック

**ステータス:** 未対処。次回 generate でも同じ偏りが出ると読者に飽きられる。

---

## メモ（未昇格・観察中）

- 構成パターンが zenn/note 両方とも `standard` 固定で選ばれた。
  `structure_selection` ロジックが入力特徴を見ているか要確認。1回だけの観測
  なので様子見。次回も全部 standard なら昇格して調査。
