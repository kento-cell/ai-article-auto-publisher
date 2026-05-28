"""Expand k_beauty / k_culture topic pool + shorten cooldown for the
2026-05-28 growth pivot (14→500 follower plan).

Current bottleneck (audited 2026-05-28):
  - cooldown_map has 53/54 topics tracked
  - 35 topics on cooldown at any given moment
  - k_beauty: 5/6 on cooldown / k_culture: 2/3 on cooldown
  - generate falls back to ai_literacy + self_improvement instead

Changes:
  1. Reduce cooldown_days for k_beauty/k_culture/ai_sidejob from 30-60
     to **7 days** — enables rapid topical cycling within the priority
     lanes. Other categories left untouched (they're zero-weighted
     anyway).
  2. Add 8 new k_beauty topics + 4 new k_culture topics to expand pool.
     New topics target sub-niches that don't overlap with existing:
       k_beauty new: PDRN / エクソソーム / リジュランブースター / 美容医療×ホームケア
                     / トラブル別 緊急ケア / アンチエイジング科学 / シカ完全解剖
                     / 化粧水・美容液テクスチャー比較
       k_culture new: 韓国カフェ最新トレンド / 韓国アイドル メイクテク
                      / 韓国ファッション 2026春夏 / 韓国式美容医療
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = Path(__file__).resolve().parent.parent
TOPICS_PATH = _REPO / "data" / "knowledge_topics.json"

NEW_COOLDOWN_DAYS = {
    "k_beauty": 7,
    "k_culture": 7,
    "ai_sidejob": 7,
    "ai_literacy": 14,
    "self_improvement": 14,
}

NEW_TOPICS = [
    {
        "id": "kb_pdrn",
        "category": "k_beauty",
        "persona": "20-30代女性、肌の悩みが深く、再生系成分に興味",
        "intent": "informational",
        "pain": "PDRN (サーモンDNA) が話題だが、本当に効くのか / 副作用は / 自宅 vs クリニック どちらか分からない",
        "promise": "PDRNの科学的根拠、自宅ケア商品 (Rejuran系) と美容医療の境界、安全に始める順序を提示",
        "outline": "PDRN とは / 韓国でのブーム理由 / 自宅ケア商品比較 / クリニック施術との違い / 副作用と禁忌 / 始める順序",
        "evidence_required": ["公式論文 or 臨床データURL", "ブランド公式URL", "クリニック施術費用相場"],
        "affiliate_family": "k_beauty",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["医療効果を断定しない", "個人の感想を一般化しない"],
    },
    {
        "id": "kb_exosome",
        "category": "k_beauty",
        "persona": "30-40代女性、エイジングケア真剣派、最新成分を試したい",
        "intent": "informational",
        "pain": "エクソソームが流行しているが、自宅ケア商品が玉石混淆。本物 vs 名ばかり をどう見分けるか",
        "promise": "エクソソーム成分の科学、信頼できるブランド (Cellbn / Beauty of Joseon etc.) の見分け方、効果実感までの目安期間",
        "outline": "エクソソームとは / 美容医療 vs 自宅ケア / 信頼できるブランド3-5社 / 偽物の見分け方 / 効果実感のタイムライン / 値段の妥当性",
        "evidence_required": ["臨床論文URL", "ブランド公式URL", "成分認証情報"],
        "affiliate_family": "k_beauty",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["未認可成分を推奨しない", "個人医療と自宅ケアの境界を曖昧にしない"],
    },
    {
        "id": "kb_rejuran",
        "category": "k_beauty",
        "persona": "30-40代女性、リジュラン注射経験者 or 検討中",
        "intent": "informational",
        "pain": "リジュラン注射後のホームケアで効果を最大化したいが、何を組み合わせるべきか分からない",
        "promise": "リジュラン施術後 4 週間の自宅ケアスケジュール、相性の良い成分 (PDRN/レチノール/シカ) の組み合わせ、避けるべきもの",
        "outline": "リジュランとは / 施術後 1-2週: 鎮静期 / 3-4週: 再生支援期 / 相性 OK 成分 / 相性 NG 成分 / 価格帯別おすすめ商品",
        "evidence_required": ["クリニック公式 URL", "成分相性の臨床根拠", "ブランド公式 URL"],
        "affiliate_family": "k_beauty",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["施術効果を保証しない", "クリニック特定の宣伝を避ける"],
    },
    {
        "id": "kb_trouble_emergency",
        "category": "k_beauty",
        "persona": "20-30代女性、急な肌トラブル発生時",
        "intent": "transactional",
        "pain": "急に赤み/ニキビ/乾燥/かぶれが出た時、韓国コスメで何を使えば早く治るか分からない",
        "promise": "トラブル別 緊急ケア 5 ステップ + K-beauty おすすめ救急アイテム (鎮静/抗炎症/再生) を症状別に即提示",
        "outline": "症状別判定フロー / 赤み・ヒリつき / ニキビ・吹き出物 / 乾燥・ひび割れ / かぶれ・かゆみ / 受診目安",
        "evidence_required": ["皮膚科学公式情報", "ブランド公式 URL", "成分の作用機序"],
        "affiliate_family": "k_beauty",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["受診を否定しない", "重症化サインを軽視しない"],
    },
    {
        "id": "kb_antiaging_science",
        "category": "k_beauty",
        "persona": "30-40代女性、エビデンス重視のエイジングケア層",
        "intent": "informational",
        "pain": "韓国コスメのアンチエイジング商品が多すぎ、本当に科学的根拠があるのは何か見分けたい",
        "promise": "K-beauty アンチエイジング核成分 (レチノール / ナイアシンアミド / ペプチド / グロスファクター) の臨床根拠と、実在ブランドの正しい使い方",
        "outline": "成分カテゴリ4 大柱 / 各成分の臨床データ / ブランド別 配合濃度比較 / 朝晩使い分け / 効果実感まで何ヶ月",
        "evidence_required": ["査読論文 URL", "FDA/食薬処データ", "ブランド公式 URL"],
        "affiliate_family": "k_beauty",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["濃度や効能を誇張しない", "未承認の併用を推奨しない"],
    },
    {
        "id": "kb_cica_deep",
        "category": "k_beauty",
        "persona": "敏感肌 / 揺らぎ肌の 20-40代女性",
        "intent": "informational",
        "pain": "シカが流行しているが、各ブランドの違いと本当に肌に合うかどう判断するか分からない",
        "promise": "シカ (Centella Asiatica) 完全解剖: 成分構造 / ブランド別配合比 / 肌タイプ別おすすめ商品 / NG 組み合わせを徹底比較",
        "outline": "シカとは / マデカソサイド vs アジアチコサイド / 主要ブランド5社比較 / 肌タイプ別おすすめ / NG 組み合わせ / 効果を最大化する順序",
        "evidence_required": ["成分論文 URL", "ブランド公式成分表", "@cosme 第三者レビュー"],
        "affiliate_family": "k_beauty",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["特定ブランドを過剰宣伝しない", "個人差を無視しない"],
    },
    {
        "id": "kb_texture_compare",
        "category": "k_beauty",
        "persona": "韓国コスメ初心者 - 中級者、 商品選びで迷う層",
        "intent": "informational",
        "pain": "化粧水・美容液のテクスチャー (とろみ・水様・ジェル・オイル) で何を選べばよいか分からない",
        "promise": "K-beauty 化粧水/美容液 テクスチャー別マッピング 20 商品 + 季節・肌悩み別の選び方",
        "outline": "テクスチャー5分類 / 水様 / さっぱりジェル / とろみ / クリーム / オイル / 季節別 / 肌悩み別 / 値段帯別おすすめ",
        "evidence_required": ["商品公式 URL", "テクスチャー画像 (@cosme公式)", "全成分表"],
        "affiliate_family": "k_beauty",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["効能ではなく使用感の話に終始しない (実成分も触れる)"],
    },
    {
        "id": "kb_medical_home",
        "category": "k_beauty",
        "persona": "20-40代女性、美容医療 + ホームケア を組み合わせたい層",
        "intent": "informational",
        "pain": "美容医療施術 (HIFU / ダーマペン / レーザー) 後の自宅ケアで K-beauty 何を使うべきか",
        "promise": "施術別 (HIFU / ダーマペン / レーザートーニング) のダウンタイムケア + 維持期に最適な K-beauty 商品マッピング",
        "outline": "美容医療 3 施術概要 / 施術後 1 週ケア / 1 ヶ月維持ケア / 避けるべき成分 / 相性 OK 成分 / 月コスト目安",
        "evidence_required": ["クリニック公式 URL", "成分相性データ", "K-beauty ブランド公式"],
        "affiliate_family": "k_beauty",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["医療と自宅ケアの境界を曖昧にしない", "施術効果を保証しない"],
    },
    # ----- k_culture additions -----
    {
        "id": "kc_cafe_trend",
        "category": "k_culture",
        "persona": "20-30代女性、韓国カフェ巡り好き、 2026 年最新動向を知りたい",
        "intent": "informational",
        "pain": "韓国の最新カフェトレンド (ベーカリー / 韓国茶 / カフェ&アトリエ) で東京で行けるところを知りたい",
        "promise": "2026春の韓国カフェトレンド3-5 軸 + 東京で類似体験できる実店舗を Instagram URL 付きで提示",
        "outline": "韓国カフェ 2026 トレンド3軸 / 韓国茶ブーム / ベーカリー復権 / カフェ&アトリエ融合 / 東京で類似店4-6軒",
        "evidence_required": ["韓国メディア記事URL", "店舗公式 Instagram URL", "メニュー写真"],
        "affiliate_family": "k_culture",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["チェーン店は紹介しない (個人店のみ)", "架空の店名を作らない"],
    },
    {
        "id": "kc_idol_makeup",
        "category": "k_culture",
        "persona": "10-20代女性、K-POP 推し、 推しメイクを真似たい層",
        "intent": "informational",
        "pain": "推しメンバーのメイクテクニックを真似したいが、 日本で手に入る K-beauty 商品でどう再現するか分からない",
        "promise": "K-POP 4 世代 主要グループ メンバー別 メイク 3-5 タイプ + 再現に必要な日本入手可能商品 (税込価格付き)",
        "outline": "推しメイク3-5タイプ抽出 / 各タイプの肌作り / ベース / アイ / リップ / 商品3点ずつ / 価格合計",
        "evidence_required": ["公式SNS写真URL", "公式メイクアップアーティストインタビュー", "商品公式URL"],
        "affiliate_family": "k_culture",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["メンバー個人情報を推測しない", "公式ソース以外のスタイリストコメントを引用しない"],
    },
    {
        "id": "kc_fashion_2026ss",
        "category": "k_culture",
        "persona": "20-30代女性、ファッション感度高い、韓国トレンド追跡層",
        "intent": "informational",
        "pain": "2026春夏の韓国ファッショントレンドを日本で取り入れたいが、何が hot で何が古いか分からない",
        "promise": "2026 SS 韓国ファッション5主軸 + 日本で手に入るブランド (3CE / Stylenanda / KIRSH 等) と日本ブランド代替案",
        "outline": "5主軸トレンド抽出 / 各トレンドの代表アイテム / 韓国ブランド購入経路 / 日本ブランド代替 / 価格帯別コーディネート",
        "evidence_required": ["韓国メディア記事URL", "ブランド公式 URL", "Instagram コーデ写真"],
        "affiliate_family": "k_culture",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["著作権侵害になる芸能人写真を貼らない", "ブランドロゴ盗用を避ける"],
    },
    {
        "id": "kc_kbeauty_medical",
        "category": "k_culture",
        "persona": "30-40代女性、韓国式美容医療に興味、 渡韓 or 国内クリニック検討中",
        "intent": "informational",
        "pain": "韓国式美容医療 (リフトアップ / 肌再生 / ダーマペン+成長因子) のトレンドと日本で受けられる場所を知りたい",
        "promise": "2026 韓国美容医療トップトレンド5 + 日本で受けられるクリニック比較 (3-5院) + 渡韓 vs 国内 コスト比較",
        "outline": "韓国美容医療5トレンド / 各施術の概要 / 日本で受けられるクリニック3-5院 / 価格・実績比較 / 渡韓のメリデメ",
        "evidence_required": ["クリニック公式URL", "施術データ", "渡韓ツアー会社公式"],
        "affiliate_family": "k_culture",
        "rotation_weight": 11.0,
        "cooldown_days": 7,
        "prohibited_angles": ["医療広告ガイドライン違反を避ける", "効果保証は禁止"],
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry-run)")
    args = ap.parse_args()

    data = json.loads(TOPICS_PATH.read_text(encoding="utf-8"))
    topics = data.get("topics", [])
    existing_ids = {t.get("id") for t in topics}

    # 1. Shorten cooldown for priority categories.
    cooldown_changes = 0
    for t in topics:
        cat = t.get("category")
        if cat not in NEW_COOLDOWN_DAYS:
            continue
        new_cd = NEW_COOLDOWN_DAYS[cat]
        if int(t.get("cooldown_days") or 30) != new_cd:
            t["cooldown_days"] = new_cd
            cooldown_changes += 1
    print(f"cooldown_days shortened: {cooldown_changes} topics")

    # 2. Add new topics (skip dups).
    added = 0
    for new_t in NEW_TOPICS:
        if new_t["id"] in existing_ids:
            print(f"  skip-dup: {new_t['id']}")
            continue
        topics.append(new_t)
        added += 1
        print(f"  added: {new_t['id']} ({new_t['category']})")

    print(f"\nnew topics added: {added}")
    print(f"final topic count: {len(topics)}")

    # Per-category eligibility preview (assuming all eligible, no cooldown).
    from collections import Counter
    eligibility = Counter()
    weights = {}
    for t in topics:
        raw = t.get("rotation_weight")
        if raw is None or raw == "":
            rw = 1.0
        else:
            try: rw = float(raw)
            except (TypeError, ValueError): rw = 1.0
        if rw <= 0 or t.get("disabled_reason"):
            continue
        cat = t.get("category", "?")
        eligibility[cat] += 1
        weights[cat] = weights.get(cat, 0) + rw
    print("\nPost-state eligible pool (ignoring cooldown):")
    total_w = sum(weights.values())
    for cat in sorted(weights, key=lambda c: -weights[c]):
        print(f"  {cat:20s} {eligibility[cat]:3d} topics × total weight "
              f"{weights[cat]:6.1f}  ({100*weights[cat]/total_w:5.1f}%)")

    if args.apply:
        TOPICS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nAPPLIED — wrote {TOPICS_PATH.relative_to(_REPO)}")
    else:
        print("\nDRY-RUN — pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
