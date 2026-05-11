"""One-shot: append 10 fresh AI×副業 topics to data/knowledge_topics.json.

Designed 2026-05-11 for a batch generation request. Each topic:
- Pillar=ai_sidejob, weight=5.0 to dominate today's sampling
- Concrete tools that actually exist (no hallucination bait)
- Pain → promise pair grounded in real monetization paths
- evidence_required forces the LLM to cite first-party sources
- prohibited_angles blocks the failure modes we've already seen
  (made-up earnings, fake creator names, get-rich-quick framing)

Safe to re-run: idempotent on `id` collisions.
"""
from __future__ import annotations

import json
from pathlib import Path

_POOL = Path(__file__).resolve().parent.parent / "data" / "knowledge_topics.json"

NEW_TOPICS: list[dict] = [
    {
        "id": "ai_004",
        "category": "ai_sidejob",
        "persona": "デザインスキル無しでデジタル商品を売りたい20-30代",
        "intent": "transactional",
        "pain": "Notionテンプレを売って稼ぐと聞くが、何を作って・どこで売って・どう宣伝すれば売れるのか動線が分からない",
        "promise": "Notion AIで作る『売れるテンプレ』の型と、Gumroad / note / BOOTH 比較、購入導線の最低限の宣伝設計を提示",
        "outline": "売れているテンプレの共通点 / テンプレ設計の3ステップ / 販売先比較 (Gumroad / note / BOOTH の手数料・客層) / 商品ページの書き方 / X / Threads での宣伝動線 / 価格設定の根拠 / まとめ",
        "evidence_required": [
            "Notion公式テンプレギャラリー",
            "Gumroad / note / BOOTH 公式の手数料ページ",
            "Notion公開クリエイターの実販売事例 (公開数字のみ)"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "『月◯◯万円達成』と未確認の収益を断定しない",
            "存在しないテンプレ販売者名を作らない"
        ]
    },
    {
        "id": "ai_005",
        "category": "ai_sidejob",
        "persona": "自動化スキルを身につけて受託副業を始めたい非エンジニア",
        "intent": "informational",
        "pain": "Make / Zapier / n8n が話題だが、副業として『何を作って』『いくらで売れるのか』が見えない",
        "promise": "Make / Zapier / n8n を比較し、副業受託で組める業務自動化レシピを5パターン示し、各々の想定単価を提示",
        "outline": "3ツール比較 (料金 / 学習コスト / 連携サービス数) / レシピ1: 議事録要約自動化 / レシピ2: 問い合わせ対応一次返信 / レシピ3: SNS投稿スケジューラ / レシピ4: 経費精算リマインダ / レシピ5: 受注→請求書生成 / 単価相場 (ココナラ / Lancers / 直契約) / まとめ",
        "evidence_required": [
            "Make / Zapier / n8n 公式料金ページ",
            "ココナラ / Lancers の自動化案件公開価格",
            "n8n公式テンプレギャラリー"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "プラットフォーム規約違反になる自動化を勧めない (DM一斉送信等)",
            "競合をdisる比較表現は避ける"
        ]
    },
    {
        "id": "ai_006",
        "category": "ai_sidejob",
        "persona": "TikTok / Shorts クリエイター志望、AI ツールで制作効率を上げたい",
        "intent": "transactional",
        "pain": "AI で動画を作って収益化したいが、CapCut / Eleven Labs / Suno / Pika などツールが多すぎて、収益化までの最短ルートが分からない",
        "promise": "TikTok 短尺動画を AI ツールスタックで量産し、収益化条件 (TikTok Creator Rewards / YouTube Partner) に乗せるまでの実践手順",
        "outline": "現状の TikTok / Shorts 収益化条件 (2026年5月時点) / ツールスタック (CapCut + Eleven Labs + Suno + Pika or Runway) / ジャンル選定 (ペット系 / 解説系 / モチベ系) / 1日1本量産フロー / 著作権・規約上の注意 / 発信開始から収益化までの目安 / まとめ",
        "evidence_required": [
            "TikTok Creator Rewards 公式ヘルプ",
            "YouTube Partner Program 公式要件",
            "Eleven Labs / Suno 商用利用ライセンスページ"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "他クリエイターの収益額を断定しない",
            "ディープフェイク / なりすまし系の使い方は紹介しない"
        ]
    },
    {
        "id": "ai_007",
        "category": "ai_sidejob",
        "persona": "ストックフォト/AI 画像販売で月数万円の不労収入を作りたい",
        "intent": "informational",
        "pain": "AI 画像でストックフォト販売が儲かるという話を聞くが、Adobe Stock / Shutterstock / Pixta の現在のAI画像ポリシーと売れ筋ジャンルが見えない",
        "promise": "2026年時点の各プラットフォームのAI画像受付ポリシーと売れ筋ジャンル、申請が通るアップロードの作法を整理",
        "outline": "ストックフォトの基本収益構造 / Adobe Stock の最新AIポリシー / Shutterstock の最新AIポリシー / Pixta の最新AIポリシー / 売れているAI画像のジャンル傾向 / 申請が落ちる典型理由 / 1日1時間運用のコツ / まとめ",
        "evidence_required": [
            "Adobe Stock コントリビューターガイドライン",
            "Shutterstock contributor 公式 AI 画像ポリシー",
            "Pixta AI 画像販売ガイドライン"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "他のクリエイターの売上を捏造しない",
            "プラットフォームポリシーは『2026年5月時点で◯◯』と日付を明示"
        ]
    },
    {
        "id": "ai_008",
        "category": "ai_sidejob",
        "persona": "ITスキル中級者、AI チャットボット構築の受託で月10-20万円を狙いたい",
        "intent": "transactional",
        "pain": "Dify / Voiceflow / Botpress でチャットボット構築の案件があると聞くが、案件単価・納品物・必要スキルが具体的に見えない",
        "promise": "Dify / Voiceflow を中心に、AI チャットボット構築代行の案件タイプ別 (FAQ / 予約 / カスタマーサポート) 単価レンジと納品フローを整理",
        "outline": "AI チャットボット市場 / Dify / Voiceflow / Botpress 比較 / 案件タイプ別単価 (FAQ / 予約 / EC接客 / 社内ヘルプデスク) / 必要スキル / 営業ルート (ココナラ / Lancers / 直営業) / 納品とサポート契約 / まとめ",
        "evidence_required": [
            "Dify / Voiceflow / Botpress 公式料金",
            "ココナラ / Lancers のチャットボット構築案件公開価格",
            "OpenAI / Anthropic API 料金ページ"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "未確認の案件数や受注数を断定しない",
            "OpenAI / Anthropic の SLA を勝手に保証しない"
        ]
    },
    {
        "id": "ai_009",
        "category": "ai_sidejob",
        "persona": "プロンプト設計に強い20-30代、デジタル商品で副収入を作りたい",
        "intent": "transactional",
        "pain": "Gumroad で AI プロンプト集が売れていると聞くが、価格設定・カテゴリ選定・宣伝動線が見えない",
        "promise": "Gumroad で AI プロンプト集 (ChatGPT / Claude / Midjourney 用) を売るための、商品設計・価格・LP・SNS宣伝の最小セットを提示",
        "outline": "プロンプト集が売れる理由 / Gumroad と note / BOOTH の比較 / 売れるカテゴリ (ライティング / マーケ / 画像生成 / コード生成) / 商品ページ7要素 / 価格設定 (低単価×量 vs 高単価×厚み) / X / Threads での集客動線 / アップデート運用 / まとめ",
        "evidence_required": [
            "Gumroad 公式ガイド (Creator Resources)",
            "公開クリエイターの実販売実績 (本人公開数字のみ)",
            "Stripe / PayPal の手数料公式ページ"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "存在しない販売者名を作らない",
            "『誰でも100万円』のような誇大表現を避ける"
        ]
    },
    {
        "id": "ai_010",
        "category": "ai_sidejob",
        "persona": "AI副業 0→1 で挫折した経験者、再挑戦のロードマップが欲しい",
        "intent": "informational",
        "pain": "AI 副業を始めたいが、何を学んで・何を作って・どう売るかの順番がバラバラで進まない",
        "promise": "完全未経験から AI 副業で月5万円ラインに乗せるための30日学習ロードマップを、週単位タスクで分解",
        "outline": "前提整理 (時間予算 / スキルの初期値) / Week1: ChatGPT / Claude の基礎運用 / Week2: 1ツール深掘り (自分の強み×AI) / Week3: 商品/サービス1個を作る / Week4: 販売チャネル開設 + 初売上 / よくある詰まり / 30日後の伸ばし方 / まとめ",
        "evidence_required": [
            "OpenAI / Anthropic 公式チュートリアル",
            "実在する学習プラットフォーム (Udemy / Coursera / YouTube公式)",
            "公開クリエイターの実体験記事 (note / Zenn) — URLを明記"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "成功保証はしない",
            "存在しないオンラインスクール名を作らない"
        ]
    },
    {
        "id": "ai_011",
        "category": "ai_sidejob",
        "persona": "BGM / SE 制作で副収入を得たいクリエイター",
        "intent": "transactional",
        "pain": "Suno / Udio で BGM を作って売れると聞くが、商用利用ライセンス・販売先・YouTube クリエイター向けの売り方が見えない",
        "promise": "Suno / Udio で生成した BGM / SE を、商用利用 OK の販売先 (Audiio / BGMer 等) で出すための、ライセンス / 制作フロー / 価格設定を整理",
        "outline": "Suno / Udio の商用ライセンス最新情報 / 販売プラットフォーム比較 (Audiio / BGMer / Pond5 など) / 1日5曲制作フロー / YouTube クリエイターへの直販ルート / 価格設定 / 著作権上の注意 / 月収シミュレーション / まとめ",
        "evidence_required": [
            "Suno / Udio 公式の商用ライセンス条項",
            "Audiio / BGMer / Pond5 の出品ガイドライン",
            "YouTube 音楽ライブラリの実際のクリエイター利用例"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "ライセンス条項は『2026年5月時点』と日付明示",
            "他クリエイターの収益額を捏造しない"
        ]
    },
    {
        "id": "ai_012",
        "category": "ai_sidejob",
        "persona": "情報収集系のリサーチ代行で受託副業を作りたい",
        "intent": "transactional",
        "pain": "Perplexity / Felo / GenSpark などリサーチ系 AI が増えたが、これを使ってどう案件化するかが見えない",
        "promise": "Perplexity / Felo / GenSpark を使ったリサーチ代行案件のタイプ別単価と、納品物のフォーマット、クライアントの探し方を整理",
        "outline": "AI リサーチ系ツール比較 (Perplexity / Felo / GenSpark / Consensus) / 案件タイプ (市場調査 / 競合分析 / 法令調査 / 専門書まとめ) / 単価レンジ / 納品物フォーマット (Notion / Google Docs / Markdown) / 営業ルート (ココナラ / Lancers / 直営業) / 信頼性の担保 (出典明示の作法) / まとめ",
        "evidence_required": [
            "Perplexity / Felo / GenSpark 公式機能ページ",
            "ココナラ / Lancers のリサーチ系案件公開価格",
            "公開クリエイターの体験記事 (URL明記)"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "AI 出力をそのまま納品する低品質パターンを推奨しない",
            "ツールの精度を断定的に保証しない"
        ]
    },
    {
        "id": "ai_013",
        "category": "ai_sidejob",
        "persona": "ライティング副業で月3万円→10万円にスケールアップしたい",
        "intent": "informational",
        "pain": "Claude / ChatGPT を使えば速く書けると分かったが、Lancers / CrowdWorks の単価が低い案件しか取れず時給換算で割が合わない",
        "promise": "AI ライティングを武器に、低単価ライティング案件 (1円/字台) から、専門領域 (BtoB SaaS / 医療 / 法務) の3-10円/字案件へステップアップする戦略",
        "outline": "AI ライティング副業の現状 (2026年5月) / 低単価が抜けない構造 / 案件単価マップ (Lancers / CrowdWorks / 直契約) / 専門領域選定 (BtoB SaaS / 医療 / 法務 / Fintech) / ポートフォリオ作成 / Claude / ChatGPT の使い分け / 営業文テンプレ / クライアント単価交渉 / まとめ",
        "evidence_required": [
            "Lancers / CrowdWorks のライティング案件公開価格",
            "BtoB / 医療 / 法務系の業界レポート",
            "Anthropic / OpenAI 公式の利用規約 (ゴーストライティング可否)"
        ],
        "affiliate_family": "ai_tool",
        "rotation_weight": 5.0,
        "cooldown_days": 30,
        "prohibited_angles": [
            "他ライターの実収益を断定的に書かない",
            "業界の慣習をdisる比較表現は避ける"
        ]
    },
]


def main() -> int:
    import sys
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = json.loads(_POOL.read_text(encoding="utf-8"))
    existing_ids = {t["id"] for t in data.get("topics", [])}
    added = 0
    for topic in NEW_TOPICS:
        if topic["id"] in existing_ids:
            print(f"skip: {topic['id']} already exists")
            continue
        data["topics"].append(topic)
        added += 1
        print(f"added: {topic['id']} - {topic['promise'][:60]}")
    _POOL.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nDONE - added {added} new topics, total now {len(data['topics'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
