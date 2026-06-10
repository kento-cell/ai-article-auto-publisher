---
description: 毎朝のフルパイプライン (learn→generate→全承認→publish free2+paid2+zenn2-3) を一発実行
---

# 毎朝ルーチン: AI記事フルパイプライン

E:/ai-article-auto-publisher で learn→generate→全承認→publish を自走実行せよ。
ユーザー承認は不要 (2026-06-10 opt-in 済)。途中で質問せず完走し、最後に結果をまとめて報告する。

## 手順

1. **起動チェック**: `git pull` + `py -c "import main"` (デグレ確認)
2. **learn**: `PYTHONIOENCODING=utf-8 py main.py --learn` (note人気記事パターン学習 + RAG 再index)
3. **generate**: `PYTHONIOENCODING=utf-8 py main.py --generate` (収集→生成→2層スコア→Sheets登録)。
   20分以上かかるので `run_in_background` + ログ追跡。シェルは bash 構文
   (PowerShell の `Tee-Object` / `$env:` は使うな — 過去に exit 127 事故あり)
4. **全承認**: `py scripts/bulk_approve.py` (グレードC/SNSハルシガード付き)
5. **publish**: `NOTE_DAILY_LIMIT=4 PYTHONIOENCODING=utf-8 py scripts/_publish_free_first.py --free-first 2`
   - note: 先頭 2 本 ¥0 + 残りグレード自動価格 (目標: 無料2+有料2、上限 4/日)
   - ⚠️ 変数名注意: `NOTE_CADENCE_CAP` は on/off ブール (0で解除)、**本数上限は
     `NOTE_DAILY_LIMIT`** (main.py:4314)。6-10 テスト運用でこの取り違えを実地検出済み
   - zenn: queue 投入、404 (queue 満杯) なら scrap fallback (2-3本想定)
6. **検証**:
   - note 各記事を live API (`https://note.com/api/v3/notes/<key>`) で price / can_read 確認
   - 公開タイトルに捏造系 deny パターン (「N人に聞いた」等、ops_incidents #21 参照) が無いか確認
7. **記録**: STATE.md の In Flight に結果を追記して commit & push

## 絶対ルール

- **品質ゲート (A/B/C) は緩めない** — 不合格記事を無理に通さず、合格した分だけ publish
- ChatGPT 画像が CDP 未起動で失敗 → Unsplash fallback のまま続行してよい
- 有料記事の membership auto-add 失敗 (既知) → STATE.md の手動追加リスト (Next Actions #1) に追記するだけでよい
- エラー時は無限リトライせず、STATE.md の Known Issues に記録して終了
- 二重実行注意: 同日にすでに pipeline 実行済みなら (STATE.md / Sheets で確認)、generate からやり直さず未 publish 分の publish だけ行う
