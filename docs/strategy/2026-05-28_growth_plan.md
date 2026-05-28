# note Growth Plan — 14 → 500 in 12 months

**Created**: 2026-05-28
**Target deadline**: 2027-05-28
**Account**: https://note.com/note-user

## Cold facts (start state)

- フォロワー: **14 人** (測定済、 ユーザー報告 2026-05-28)
- 公開記事: 157 件 (うち engagement 紐付け 129 件)
- 上位記事 ♥3-5 / 7-10 日 → engagement rate **20-35%** (audience に対して異常に高い)
- membership: **0 件** (UI bug で 20 件 backlog 含む)
- note Premium: **無し** (契約予定なし)
- 既存ジャンル: K-beauty / 韓国 / グルメ / lifestyle / AI 副業 (散乱)

## 真の問題

「audience が小さい」 ではなく 「**discovery 経路がない**」。
- engagement rate 20-35% = 既読者の質は良い
- 公式マガジン pickup ゼロ = アルゴ + editor 露出ゼロ
- X account 無し = cold traffic 流入経路ゼロ
- ジャンル散乱 = hashtag page で「この人は何の人か」 判別不能

## 目標数式

```
14 × (1 + r)^12 = 500
r ≈ 35.4%/月
```

S 字成長想定:
- M1-3: 14 → 50-80 (基盤整備、 月 +25-30%)
- M4-9: 80 → 250-350 (X funnel + マガジン pickup 累積、 月 +30-40%)
- M10-12: 350 → 500 (membership 化開始で離脱微増、 月 +15-25%)

達成に必要なレバー:
1. **公式マガジン pickup 月 1 回 = +200-500 フォロワー/回** (達成すれば 1 回で目標近接)
2. **X account 連動で月 +20-50 フォロワー** (継続安定枠)
3. **初速の法則 + tag 規律** で 1 publish あたり reach 5-10x

## ジャンル方針 (確定)

| 比重 | lane | 用途 |
|---|---|---|
| 70% | K-beauty / 韓国カルチャー | 主軸、 内部データで唯一安定勝ち、 audience も寄ってる |
| 20% | AI × 副業 (実務寄り) | 副軸、 9 月本業入社の brand と整合 |
| 10% | 橋渡し (AI × K-beauty) | 「ChatGPT で韓国 skincare 翻訳」 「AI 成分分析」 等、 両 lane 相互受給 |
| 0% | グルメ / lifestyle / 政治 / minimalism | seed 除外、 generate 対象外 |

## 戦術 (フェーズ別)

### Phase 0: 足元固め (今週、 30 分-2 時間)

- **publish 1 本/日 hard-cap** (`main.py::publish_approved` + Slack bot 両方) — suspension 回避最優先
- **ユーザータスク**: note プロフィール文 + 過去 30 記事から「AI 自動生成」 言及削除
- **ユーザータスク**: membership 20 件 backlog をダッシュボード手動消化 (audience が育つ前に conversion 経路を生かしておく)

### Phase 1: 自動化基盤 (1-2 日)

- `config/settings.yaml` + `data/knowledge_topics.json` の rotation_weight を 70/20/10 に再配分
- `config/prompts.yaml` で全 publish に 3-5 tags (1 broad + 2-4 narrow) を出力必須化
- `scripts/_publish_at_slot.py` — 火 19-22 / 金 17:00 / 日 11-14 の slot 投稿スクリプト
- generate は前夜 stage、 publish は slot に bot trigger の半手動運用

### Phase 2: discovery 経路を作る (30-60 日)

- **Magnet 大型 free 記事 1-2 本投入** — 候補:
  - 「韓国コスメ実店舗購入マップ 30 軒 — 都内全エリア、 Instagram URL + 公式 web 完全網羅」 (share/save 用)
  - 「K-beauty 全成分辞典 50 項目 — 効能/合成/避ける肌タイプ/ブランド対応一覧」 (検索流入用)
- **X account (K-beauty 専用) 立ち上げ** — daily で韓国コスメ news/ 新発売 quote + insight thread
- **公式マガジン pickup 狙い** — tag 規律 + 月次 [note.com/magazine/official](https://note.com/magazine/official) で curation 傾向 check

### Phase 3: スケール (60-90 日 〜 1 年)

- 初速 slot publish が定常化 (火 / 金 / 日 の 3 回/週 ペース)
- X follower 1,000-2,000 で note funnel が機能
- 90 日後に membership 再構造化検討 (¥500 試し + ¥1,020 maintained + live element 追加)

## 90 日 / 1 年 KPI

| metric | 現状 | 30 日 | 90 日 | 1 年 |
|---|---|---|---|---|
| note フォロワー | **14** | 30-50 | 80-150 | **500** |
| 月次 ♥ 中央値 | 1-2 | 3-5 | 5-10 | 10-20 |
| 公式マガジン pickup | 0 累計 | 0-1 累計 | 1-2 累計 | 4-6 累計 |
| X フォロワー (K-beauty) | 0 | 100-200 | 500-800 | 2,000-3,000 |
| membership | 0 | 0 (UI 修復) | 0 (audience 待ち) | 20-50 |

## 必要な user side action (CC 不可能)

1. note プロフィール文編集 (「AI で自動生成」 等の文言削除) — 5 分
2. membership 20 件 backlog のダッシュボード手動追加 — 30 分 x 1 回
3. X account 開設 + プロフィール設定 (K-beauty 専用、 アイコン + bio) — 30 分
4. note 公式マガジン curation 傾向 月次 check — 10 分/月

## 関連実装ファイル

- 比重調整: `config/settings.yaml` `data/knowledge_topics.json`
- tag 規律: `config/prompts.yaml` `generators/hashtag_generator.py`
- cadence cap: `main.py::publish_approved` `bot/slack_bot.py`
- slot publish: `scripts/_publish_at_slot.py` (新規)
- Magnet 記事 draft: `scripts/_magnet_k_beauty_shop_map.md` `scripts/_magnet_k_beauty_ingredient_dict.md` (新規)
