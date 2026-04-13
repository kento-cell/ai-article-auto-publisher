# ローカル作業 TODO（ユーザー宛）

このリポジトリの**コードはほぼ完成**で、稼動を本格化させるには**ユーザーがローカル
で実施しないといけない一連の手作業**が残っています。優先度と所要時間別にまとめました。

最終更新: 2026-04-13

---

## 🔴 最優先（今日中〜数日で）

### 1. GCP サービスアカウント秘密鍵の整理
- ファイル `E:\ai-article-auto-publisher\ai-publisher-492612-60f103cb499b.json`
  がリポジトリルートに置かれている (`.gitignore` 除外済 = git は安全)
- 同フォルダがクラウド同期対象でなければ即時リスクは低い
- やること:
  - [ ] このファイルを `C:\secrets\` 等 repo 外に移動
  - [ ] コード側のパスを `.env` 経由で参照するよう変更
  - [ ] (将来的に) GCPコンソールで一度ローテーションしておくと盤石
- 関連メモ: `memory/project_places_api_pending.md`

### 2. Google Places API キー貼付（ハルシネーション対策の本命）
- 取得手順: https://console.cloud.google.com/ → Google Maps Platform →
  Places API (New) を有効化 → 認証情報 → APIキーを発行
- やること:
  - [ ] APIキーを `.env` の `GOOGLE_PLACES_API_KEY=` に貼付
  - [ ] (推奨) APIキーを Places API (New) のみに制限
  - [ ] 課金: $200 無料枠で月6,000記事分は余裕。「予算とアラート」を $10 で設定推奨
- 効果:
  - グルメ系記事の店舗住所/営業時間/価格/公式URLが**実データに置換**される
  - LLM ハルシネーションが事実上ゼロに
- 関連メモ: `memory/project_places_api_pending.md`

---

## 🟡 中優先（今週中で）

### 3. アフィリエイト広告主申請（合計15件）

**ASP 登録**:
- [x] A8.net (`kanazawa2000`) ✅ 完了
- [ ] **バリューコマース** に新規登録 → メディア審査
  - https://www.valuecommerce.ne.jp/
  - note の URL を記載して申請

#### A8.net で提携申請する広告主（8件）

詳細: `docs/affiliate_setup_beauty.md` + `docs/affiliate_setup_gourmet.md`

| 優先度 | 広告主 | 想定単価 | env変数 |
|---|---|---|---|
| ★★★ | RIZAP | ¥10,000+/件 | `A8_RIZAP_LINK` |
| ★★★ | nosh (ナッシュ) | ¥3,000-¥5,000/件 | `A8_NOSH_LINK` |
| ★★★ | リゼクリニック | ¥3,000-¥5,000/件 | `A8_RIZE_LINK` |
| ★★ | Oisix | ¥1,500-¥3,000/件 | `A8_OISIX_LINK` |
| ★★ | オルビス トライアル | ¥1,000-¥1,500/件 | `A8_ORBIS_LINK` |
| ★★ | BEYOND ジム | ¥5,000-¥8,000/件 | `A8_BEYOND_LINK` |
| ★ | DHC | 売上%費 | `A8_DHC_LINK` |
| ★ | BLOOMBOX | ¥1,500-¥3,000/件 | `A8_BLOOMBOX_LINK` |
| ★ | SOELU オンラインヨガ | ¥1,500-¥3,000/件 | `A8_SOELU_LINK` |
| ★ | ミュゼ | ¥2,000-¥4,000/件 | `A8_MUSEE_LINK` |
| ★ | らでぃっしゅぼーや | ¥1,500-¥3,000/件 | `A8_RADISH_LINK` |

#### バリューコマースで提携申請する広告主（7件）

| 優先度 | 広告主 | 想定単価 | env変数 |
|---|---|---|---|
| ★★★ | 一休.comレストラン | ¥628/ディナー予約 | `VCM_IKYU_REST_LINK` |
| ★★★ | ホットペッパービューティー | ¥300-¥600/件 | `VCM_HPB_LINK` |
| ★★ | OZmall ビューティ | ¥286/件 | `VCM_OZMALL_BEAUTY_LINK` |
| ★★ | OZmall ディナー | ¥286/件 | `VCM_OZMALL_LINK` |
| ★★ | ホットペッパーグルメ | ¥100×人数 | `VCM_HOTPEPPER_LINK` |
| ★★ | さとふる | 1%/寄附額 | `VCM_SATOFUL_LINK` |
| ★★ | ふるなび | 1.1%/寄附額 | `VCM_FURUNAVI_LINK` |
|  | Yahoo!ショッピング グルメ | 売上% | `VCM_FOOD_LINK` |

#### 申請のコツ
- **メディア審査が通りやすくなるTips**: 「note の月間PV」「ジャンル特化志向」
  「実体験ベースの記事」を強調
- **記事数が少ないと審査落ちする広告主**もある（特に一休、リゼクリニック）→
  まず note 投稿数を 30-50 以上にしてから申請
- **A8 は提携申請が比較的緩い**ので先に攻めるのが効率的

#### 承認後の作業
1. ASP 管理画面で「広告リンク作成」ボタンから**テキストリンクのURL**を発行
2. `.env` の対応する `A8_*_LINK=` または `VCM_*_LINK=` に貼付
3. 確認コマンド:

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
    if total: print(f'{genre:25s}: {valid}/{total} 設定済')
"
```

---

## 🟢 低優先（落ち着いてから）

### 4. Gmail 通知の OAuth 再認可
- 現状: `unauthorized_client` エラーで Gmail 通知が落ちている
- 影響: パイプラインは動くが、承認待ち記事の通知メールが届かない
- やること: GCP コンソールで Gmail API の OAuth スコープ再認可
- 優先度低: ユーザーは Slack 通知で代用可能と判断済み

### 5. A8.net パスワード管理
- 現状: ID `kanazawa2000` のみ判明、パスワードは画像でマスク
- やること:
  - [ ] https://www.a8.net/login.html → 「パスワードを忘れた方はこちら」
  - [ ] ID + 登録メール (`kanazawaj0929@gmail.com`) で再設定
  - [ ] 新パスワードはパスワードマネージャ (Bitwarden / 1Password / Edge内蔵) に保存
  - [ ] 振込先銀行口座 (三井住友銀行渋谷支店 普通8273085) は登録済 ✅
  - [ ] デスクトップの `A8アカウント.png` を `C:\Users\kanaz\Documents\Private\` に移動

### 6. note ジャンル戦略の決定
- 現状: 雑記化（AI論文/グルメ/コーヒー/韓国/マネタイズが混在）
- リサーチ結果（`docs/knowledge/affiliate_strategies/2026-04-13_research.md`）から、
  特化サイト化が月10万円超の必須条件
- やること: 月次メインジャンル決定（例: 4月=下北沢グルメ、5月=AIツール）
- これはコード変更というより**運用方針の決定**

### 7. デスクトップのカバー画像生成済みファイル整理
- 既に `data/images/covers/` に多数の retrofit 画像が溜まっている
- 一度クリーンナップしておくとよい

---

## 🔵 完了済み（参考）

- ✅ Slack Bot 起動・認証
- ✅ Bluesky collector 統合・126エリアカバー
- ✅ Codex Web検索研究パス組み込み
- ✅ note 編集での埋め込みリンク + インライン画像 + キャプション + 免責
- ✅ Unsplash 画像を topic-themed カバーに自動採用
- ✅ チェーン店ブラックリスト + 個人店ホワイトリスト方針
- ✅ アフィリエイト 8 ジャンル定義 (グルメ4 + 美容/健康4 + 既存tech/ai/learning/etc.)
- ✅ Mermaid 自動レンダリング検証
- ✅ 数値スコア (0-100) 導入、Zenn 82.5以上で記事/未満でスクラップ
- ✅ note 記事 4本 (風神/青空カフェ部/やよい軒/なおちゃんラーメン) を編集修正済

---

## 📋 まとめ：今日の優先3アクション

1. **GCP Places API キー発行 → `.env` 貼付** (1時間)
2. **A8.net パスワード再設定** → ログイン → **RIZAP・nosh・リゼクリニックの3件だけ** 提携申請 (30分)
3. **承認来たら `.env` の対応欄に貼付** (5分/件)

これだけで月収数万円ラインに乗る土台ができます。
