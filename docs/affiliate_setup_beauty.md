# 女性向け（美容・スパ・ダイエット）アフィリエイト 申請ガイド

`config/affiliates.yaml` に追加した3ジャンル + 既存 `beauty` 拡張の登録手順。
未設定のリンクは `AffiliateInjector._is_valid_link` で**自動でフィルタ**されるので、
`.env` を空のまま運用しても記事には影響しません。

---

## 🅑 beauty（既存ジャンル拡張）

韓国コスメ・プチプラ・デパコス・スキンケアトラブル系記事をカバー。
キーワード追加済み（メイク/化粧水/美容液/毛穴/シミ/シワ/ニキビ/敏感肌 等）。

| 環境変数 | 状態 | 備考 |
|---|---|---|
| `AMAZON_TAG=satoarata-22` | ✅ 設定済 | Amazon コスメリンクが自動で動く |
| `RAKUTEN_AFFILIATE_ID` | ✅ 設定済 | 楽天美容ランキングが自動で動く |
| `AFB_BEAUTY_LINK` | ⏳ 未設定 | afb 申請が必要 |

---

## 🅢 beauty_spa_salon — スパ・サロン予約系

**月の本命候補**。一人あたりの単価が高く、女性読者の購買意欲も強い。

申請先: **A8.net** / **バリューコマース**

### 必要な申請

| 環境変数 | 広告主 | ASP | 報酬目安 | 取得方法 |
|---|---|---|---|---|
| `VCM_HPB_LINK` | ホットペッパービューティー | バリューコマース | 新規予約 ¥300〜¥600 | ValueCommerce → 広告検索「HPB」→ 提携申請 |
| `VCM_OZMALL_BEAUTY_LINK` | OZmall ビューティ | バリューコマース | 予約完了 ¥286 | ValueCommerce → 「OZmall」→ 提携申請 |
| `A8_RIZE_LINK` | リゼクリニック (医療脱毛) | A8.net | 無料カウンセリング ¥3,000〜¥5,000 | A8 → 「リゼクリニック」→ 提携申請 |
| `A8_MUSEE_LINK` | ミュゼプラチナム (脱毛サロン) | A8.net | 来店 ¥2,000〜¥4,000 | A8 → 「ミュゼ」→ 提携申請 |

---

## 🅒 beauty_cosmetics — コスメEC・サブスク系

トライアル/試供品/サンプルで成果が出やすい (購入ハードル低)。

申請先: **A8.net**

| 環境変数 | 広告主 | 報酬目安 | 取得方法 |
|---|---|---|---|
| `A8_ORBIS_LINK` | オルビス トライアル | 初回 ¥1,000〜¥1,500 | A8 → 「オルビス」 |
| `A8_DHC_LINK` | DHC公式オンライン | 売上の数% | A8 → 「DHC」 |
| `A8_BLOOMBOX_LINK` | BLOOMBOX (コスメ定期便) | 初回 ¥1,500〜¥3,000 | A8 → 「BLOOMBOX」 |
| `RAKUTEN_AFFILIATE_ID` | 楽天美容ランキング | ✅ 既に動作 | — |

---

## 🅓 wellness_diet — ダイエット・フィットネス・ウェルネス

**最高単価の本命**。パーソナルジムは1件 ¥10,000+ の報酬。

申請先: **A8.net**

| 環境変数 | 広告主 | 報酬目安 | 取得方法 |
|---|---|---|---|
| `A8_RIZAP_LINK` | RIZAP (パーソナルジム) | 無料カウンセリング ¥10,000+ | A8 → 「RIZAP」 |
| `A8_BEYOND_LINK` | BEYOND (パーソナルジム) | 体験申込 ¥5,000〜¥8,000 | A8 → 「BEYOND」 |
| `A8_SOELU_LINK` | SOELU (オンラインヨガ) | 体験 100円申込 ¥1,500〜¥3,000 | A8 → 「SOELU」 |

---

## 📋 ローカル作業チェックリスト

### 1. ASP登録 (まだなら)
- [ ] バリューコマース https://www.valuecommerce.ne.jp/
  → メディア審査あり。note の URL を記載
- [ ] A8.net https://www.a8.net/ → ✅ 既に登録済 (kanazawa2000)

### 2. 広告主提携申請 (合計13件)

A8.net の管理画面から:
- [ ] リゼクリニック
- [ ] ミュゼプラチナム
- [ ] オルビス
- [ ] DHC公式オンライン
- [ ] BLOOMBOX
- [ ] RIZAP
- [ ] BEYOND
- [ ] SOELU

ValueCommerce の管理画面から:
- [ ] ホットペッパービューティー
- [ ] OZmall ビューティ
- [ ] さとふる (ふるさと納税)
- [ ] ふるなび (ふるさと納税)
- [ ] 一休.comレストラン
- [ ] OZmall ディナー
- [ ] ホットペッパーグルメ

### 3. 承認後にリンク発行 → `.env` に貼付

```env
# A8.net 美容・ダイエット
A8_RIZE_LINK=         # ← リゼクリニックの「広告リンク作成」で発行されたURL
A8_MUSEE_LINK=
A8_ORBIS_LINK=
A8_DHC_LINK=
A8_BLOOMBOX_LINK=
A8_RIZAP_LINK=
A8_SOELU_LINK=
A8_BEYOND_LINK=

# バリューコマース 女性向け予約
VCM_HPB_LINK=
VCM_OZMALL_BEAUTY_LINK=
```

### 4. 反映確認

```bash
venv/Scripts/python.exe -c "
import os
for line in open('.env', encoding='utf-8').read().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())
from generators.affiliate_injector import AffiliateInjector
inj = AffiliateInjector()
for genre, info in inj._config['genres'].items():
    valid = sum(1 for l in info.get('links', []) if inj._is_valid_link(l['url']))
    total = len(info.get('links', []))
    if total:
        print(f'{genre:25s}: {valid}/{total} 設定済')
"
```

---

## 💰 想定収益感（女性向けジャンル合算）

PV 規模 月100記事 × 月3,000PV/記事 を想定:

| ジャンル | 月成約数 | 1件単価 | 月収目安 |
|---|---|---|---|
| beauty (Amazon/楽天) | 60 | ¥50 | ¥3,000 |
| beauty_spa_salon (HPB/リゼ) | 30 | ¥1,500 | **¥45,000** |
| beauty_cosmetics (オルビス等) | 40 | ¥1,500 | **¥60,000** |
| wellness_diet (RIZAP等) | 8 | ¥8,000 | **¥64,000** |

**合計目安: 月¥172,000** （PV伸びれば線形に増える）

ポイント:
- **wellness_diet (RIZAP等) が単価最高** — 1件¥10,000レベル
- **beauty_cosmetics (オルビス/DHC)** はトライアル系で成約しやすい
- ダイエット記事 + 「結果にコミット系」CTA、コスメ記事 + 「30日返品保証あり」CTA が王道
