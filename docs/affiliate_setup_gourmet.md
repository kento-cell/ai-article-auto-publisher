# グルメ系アフィリエイト 申請ガイド

`config/affiliates.yaml` に追加した4ジャンル（food / food_delivery / furusato /
gourmet_reservation）を**実際に稼動させる**ためのユーザー作業まとめ。

各広告主は ASP 経由で申請 → 承認 → 個別の成果リンクが発行されたら `.env` の
対応する環境変数に貼り付ける。プレースホルダーが空のリンクは
`AffiliateInjector` が自動でフィルタするので、申請が通っていない広告主は
記事に挿入されない（安全）。

---

## 🍜 food（既存ジャンル拡張）

既に動作している部分:
- ✅ `AMAZON_TAG=satoarata-22` — Amazonコーヒー豆リンク
- ✅ `RAKUTEN_AFFILIATE_ID` — 楽天お取り寄せグルメ
- ⏳ `VCM_FOOD_LINK` — 未設定

申請するもの:
- **バリューコマース** (https://www.valuecommerce.ne.jp/)
  - メディア審査が必要 → noteのURLで申請
  - 承認後、Yahoo!ショッピング のグルメカテゴリリンクを発行 → `VCM_FOOD_LINK` に貼付

---

## 🥗 food_delivery（食材宅配・ミールキット — 高単価サブスク）

このジャンルは1件成約で **¥3,000〜¥10,000** の高単価が狙える。下北沢グルメ系
記事の関連リンクとして自然に展開できる。

申請先: **A8.net** (https://www.a8.net/)

| 環境変数 | 広告主 | 報酬目安 | 検索キーワード |
|---|---|---|---|
| `A8_OISIX_LINK` | Oisix（オイシックス） | 入会1件 ¥1,500〜¥3,000 | "Oisix" |
| `A8_NOSH_LINK` | nosh（ナッシュ） | 初回購入 ¥3,000〜¥5,000 | "nosh" or "ナッシュ" |
| `A8_RADISH_LINK` | らでぃっしゅぼーや | 入会1件 ¥1,500〜¥3,000 | "らでぃっしゅぼーや" |

**手順**:
1. A8.netにログイン → 広告主検索
2. 上記広告主名で検索 → 提携申請
3. 承認後（即時 or 数日）→ 「広告リンク作成」 → テキストリンクを発行
4. URL を `.env` の対応する `A8_XXX_LINK=` に貼付

---

## 🎁 furusato（ふるさと納税 — 食品カテゴリは高利率）

楽天ふるさと納税の食品カテゴリは **料率4%** で業界トップクラス。寄附額
¥10,000 で ¥400 の報酬。ご当地グルメ記事と相性◎。

| 環境変数 | 広告主 | ASP | 報酬 |
|---|---|---|---|
| `RAKUTEN_AFFILIATE_ID`（既存） | 楽天ふるさと納税 | 楽天アフィリエイト | 食品4%、その他2% |
| `VCM_SATOFUL_LINK` | さとふる | バリューコマース | 1% / 寄附額 |
| `VCM_FURUNAVI_LINK` | ふるなび | バリューコマース | 1.1% / 寄附額 |

**楽天ふるさと納税** はすでに `RAKUTEN_AFFILIATE_ID` で動いているので、
追加申請不要（食品カテゴリへの直リンクが affiliates.yaml に既に入っている）。

**さとふる/ふるなび** はバリューコマースで広告主検索 → 提携申請 → 承認後リンク発行。

---

## 🍽️ gourmet_reservation（レストラン予約）

下北沢/恵比寿/吉祥寺など**地域グルメ記事の本命**。デート・記念日記事と特に相性◎。

申請先: **バリューコマース** (https://www.valuecommerce.ne.jp/)

| 環境変数 | 広告主 | 報酬 | 強み |
|---|---|---|---|
| `VCM_IKYU_REST_LINK` | 一休.comレストラン | 新規ディナー予約 ¥628 | 平均予約単価¥14,000、高級店中心 |
| `VCM_OZMALL_LINK` | OZmall | 予約完了 ¥286 | 女性向け、デート/記念日 |
| `VCM_HOTPEPPER_LINK` | ホットペッパーグルメ | ¥100 × 予約人数 | 宴会・大人数で累積稼ぎ |

**手順**:
1. バリューコマース 管理画面 → 「広告検索」
2. 上記広告主名で検索 → 提携申請
3. 一休は審査が厳しめ（メディア品質を見られる）— note 記事数を増やしてから申請推奨
4. 承認後 → 「広告作成」→ テキストリンク or バナー発行 → URL を `.env` に貼付

---

## 🔧 設定確認

すべての環境変数を貼り付けたら、設定を反映:

```bash
# .envをリロード
venv/Scripts/python.exe -c "
import os
for line in open('.env', encoding='utf-8').read().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())
from generators.affiliate_injector import AffiliateInjector
inj = AffiliateInjector()
# 各ジャンルで設定済みリンク数を確認
for genre, info in inj._config['genres'].items():
    valid = sum(1 for l in info.get('links', []) if inj._is_valid_link(l['url']))
    print(f'{genre:25s}: {valid}/{len(info.get(\"links\", []))} 設定済')
"
```

未設定の広告主は `AffiliateInjector._is_valid_link` でフィルタされ、
記事に挿入されない（プレースホルダー混入の心配なし）。

---

## 💰 想定収益感（月100記事 × 月3,000PV / 記事）

| ジャンル | 想定CTR | 想定CVR | 月成約数 | 1件単価 | 月収目安 |
|---|---|---|---|---|---|
| food (Amazon/楽天) | 1% | 2% | 60 | ¥30 | ¥1,800 |
| food_delivery (Oisix等) | 1.5% | 1% | 45 | ¥3,000 | **¥135,000** |
| furusato (楽天食品4%) | 2% | 3% | 180 | ¥400 | ¥72,000 |
| gourmet_reservation (一休) | 1.5% | 0.5% | 22 | ¥628 | ¥13,800 |

**合計目安: 月¥222,600**（PV/CTR/CVR の前提次第で大きくブレる）

ポイント:
- 食材宅配 (food_delivery) が単価最大 → 「下北沢の○○みたいな味を家で再現」
  系の記事で Oisix/ナッシュへの導線を作るのが効率的
- ふるさと納税 (furusato) は数で稼ぐ → ご当地グルメ記事に楽天ふるさと納税の
  該当カテゴリリンクを差し込む
- レストラン予約 (gourmet_reservation) は note の地域グルメ記事と本命の組み合わせ
