---
description: AI業界情報を西海岸/欧州の一次ソースから収集→gemma4で濃いダイジェスト→#ai-catchup へSlack送信
---

# AI情報キャッチアップ (Slack配信)

E:/ai-article-auto-publisher で **AI 業界の最新情報をローカル LLM (gemma4) で
濃いダイジェスト化**して Slack `#ai-catchup` に投げる。

## 実行手順

1. **dedup 状態確認** (前回送信からどれだけ新着があるか):
   ```bash
   PYTHONIOENCODING=utf-8 py -c "
   import sqlite3
   c = sqlite3.connect('data/catchup.db')
   print('notified:', c.execute('SELECT COUNT(*) FROM notified').fetchone()[0])
   print('last sent:', c.execute('SELECT MAX(notified_at) FROM notified').fetchone()[0])
   c.close()
   "
   ```

2. **rich catchup を本送信**:
   ```bash
   PYTHONIOENCODING=utf-8 py scripts/run_catchup.py
   ```
   実行時間: ~5-7分 (gemma4 で 22 itemを順次要約)。 `run_in_background` 推奨。
   ⚠️ `--dry` フラグでプレビュー、 `CATCHUP_DRY_RUN` env は無視されるので注意。

3. **送信結果確認** (完了通知後):
   ```bash
   LOG=<background output file>
   grep -E "posted|DONE:|messages|FAILED" "$LOG" | tail -3
   grep -oE "Generation complete \([0-9]+ chars\)" "$LOG" | grep -oE "[0-9]+" | py -c "
   import sys; v=[int(x) for x in sys.stdin]
   print(f'要約密度: n={len(v)} avg={sum(v)//len(v)} min={min(v)} max={max(v)} chars')"
   grep -cE "ご提供|お手数ですが|テキスト全文を" "$LOG" | xargs echo "refusal markers:"
   ```
   期待値: `posted N items in M Slack message(s)` / 要約 avg 350-500字 / refusal 0件

4. **品質ゲート確認**:
   - posted item ≥ 15 件 → 健全
   - avg 要約字数 < 250 → summarizer 退行を疑う (catchup/summarizer.py の _PROMPT 確認)
   - refusal markers > 0 → `_REFUSAL_RE` の guard を疑う

## 仕組み (詳細)

- ソース: `catchup/sources.py` で OpenAI/Anthropic/DeepMind/NVIDIA Developer
  /Hugging Face/Hacker News/arXiv/Reddit を fetch → tier 付け (Tier1=公式ラボ、
  Tier2=コミュニティ、 Tier3=リサーチ・雑感)
- dedup: `data/catchup.db` (SQLite) に `(source, item_id, notified_at)` で 30 日保存
- 要約: `catchup/summarizer.py` が gemma4:e4b で **6-9 行 / 400-550 字**密度。
  画像のみ source は `_looks_textless` でタイトル fallback、 refusal は `_REFUSAL_RE` で破棄
- digest: `catchup/digest.py` で Tier1=10/Tier2=7/Tier3=5 cap、 公開時刻表示
- 送信: `catchup/runner.py` の `_chunk` (<=3500 char/Slack 制限) で複数メッセージ分割

## 絶対ルール

- **gemma4 を専有するので routine の generate と同時起動禁止** (ollama 競合)
- **dedup を勝手にリセットしない** — 同じ item を二度配信する事故になる
  - 例外: 「内容が薄い、 再送して」 と user が明示した場合のみ
    `py -c "import sqlite3; c=sqlite3.connect('data/catchup.db'); c.execute('DELETE FROM notified'); c.commit()"`
- **Slack webhook が落ちていたら投稿は skip して dedup も mark しない** (`runner.py` で自動)

## 過去事故 (参考)

- 2026-06-16 朝: 旧 summarizer は 3-5行/250字で **薄すぎ**と user 指摘 →
  `06ba988` で 6-9 行 / 400-550 字 に深化、 画像のみ source の refusal guard 追加
- 2026-06-16 初回: `CATCHUP_DRY_RUN` env で dry-run できると誤認 → 薄い版を実投稿、
  dedup 全リセットで rich 再送。 dry-run は **`--dry` フラグのみ** が正規。

## 関連ファイル

- `catchup/runner.py` — pipeline 実体
- `catchup/summarizer.py` — gemma4 ダイジェスト生成
- `catchup/digest.py` — Slack mrkdwn 整形
- `catchup/sources.py` — フィード fetch
- `catchup/dedup.py` — SQLite dedup
- `scripts/run_catchup.py` — CLI エントリ
