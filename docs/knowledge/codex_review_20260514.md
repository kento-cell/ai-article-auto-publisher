前提: ローカルシェルが `CreateProcessAsUserW failed: 1312` で動かず、実行ドライランはできませんでした。GitHub 上の現行 HEAD と確認できた本日 8 commits をレビューしています。提示は「9 commits」ですが、確認できたのは 8 件です。

**Critical**

- `main.py:3160` / `generators/score_aggregator.py:142` / `generators/score_aggregator.py:218`  
  `hallu-veto sim≥0.92` が集計に効いていない可能性が高いです。`main.py` は `subj_result["dimensions"]["accuracy"]` を C にしていますが、`ScoreAggregator` は top-level の `subjective["accuracy"]` を読んでおり、`overall_grade` も最終判定に使っていません。つまり「ログ上は veto したが、最終 grade は通る」事故が起き得ます。  
  修正パッチ案: hallu-veto 時は `subj_result["accuracy"] = {"grade": "C", ...}` を直接上書きし、さらに `subj_result["blocking_issues"].append(...)` を追加してください。より安全には `forced_reject_reason` を `ScoreAggregator.aggregate()` に渡して、subjective の形に依存せず総合 C に落とす経路を作るべきです。sim 0.92 の fixture を 1 件入れて「aggregate 後も C になる」単体テストを追加してください。

- `main.py:2586` / `main.py:2625` / `main.py:3090`  
  C-rescue regen が新規ハルシネーション生成器になっています。特に word_count rescue feedback が「固有名詞・具体例・数値を厚くする」と促しており、今日観測された SAP / 2026 年 / Bluesky 偽引用のような増殖と整合します。客観 fail を救う処理なのに、救済時の fact whitelist がありません。  
  修正パッチ案: C-rescue は `allowed_fact_ledger` を必須入力にしてください。元ソース、research brief、既存引用 URL から「使用可能な固有名詞・数値・引用・日付」を構造化し、regen prompt には「この ledger 外の固有名詞・数値・引用を追加禁止」と入れる。再生成後は新旧 diff で新規の数値、大学名、企業名、人物肩書、引用表現を抽出し、ledger に無ければ即 reject。ledger が作れない記事では C-rescue を無効化すべきです。

- `main.py:4379` / `main.py:4413` / `scripts/_pillow_banner_paid_2.py:1` / `scripts/_pillow_banner_free_2.py:1`  
  サムネの自動最終形に対して、publish 本線はまだ `ChatGPT -> Unsplash` で、Pillow は手動スクリプトです。ChatGPT が note ロゴや既存画像を返す既知問題がある以上、今のままだと「文字入り目を惹くサムネを毎回」は達成できません。  
  修正パッチ案: `generators/pillow_banner_generator.py` を作り、手動スクリプトの banner 生成部を再利用可能 API に分離してください。cover cascade は `既存 cover 検証 OK -> ChatGPT 生成かつ検証 OK -> Pillow 文字入り banner -> publish fail` にします。Unsplash は cover fallback から外し、本文 inline 専用にしてください。cover 検証は `local file`, `1200x630 以上`, `min bytes`, `text_overlay=true`, `title token が入っている`, `過去 MD5 と非一致` を必須にするべきです。

- `collectors/knowledge_topics_collector.py:147`  
  portable topic exclude の `rotation_weight: 0` が `float(t.get("rotation_weight") or 1.0)` で `1.0` に戻ります。数値 0 を YAML に書くと除外にならず、今日の「portable excludes」が効かない clone が出ます。  
  修正パッチ案: `raw = t.get("rotation_weight")` として、`raw is None or raw == ""` の時だけ `1.0`、それ以外は `float(raw)` にしてください。`0`, `"0"`, `0.0` がすべて除外される単体テストを追加するのが最低ラインです。

**High**

- `config/prompts.yaml:51` / `config/prompts.yaml:282`  
  Writer prompt が「専門家の見解を統合」「○○の専門家は〜と指摘」の型を促しつつ、後段で架空引用禁止を言っています。この矛盾は「○○大学教授によれば」型ハルシを prompt 内で誘発します。  
  修正パッチ案: 「専門家の見解」は、元ソースに実名・所属・発言がある場合だけ許可に変更してください。prompt に `QUOTE_LEDGER` を渡し、`QUOTE_LEDGER` に無い人物発言、大学名、研究者肩書は禁止。sanitizer 側にも `大学|研究所|教授|専門家|関係者` + `によれば|指摘|語った|述べた` の組み合わせを検出し、引用 URL が同段落に無ければ fail する deterministic check を入れるべきです。

- `main.py:970` / `main.py:3160`  
  `sim≥0.92` は未較正です。意味検索で 0.92 はほぼ near-duplicate 用で、表現を変えた架空引用や数値捏造は素通りしやすいです。一方、単純に下げると誤爆します。  
  修正パッチ案: `scripts/eval_hallu_guard_threshold.py` を追加し、`hallucination_registry` の既知 bad と過去 approved good を使って 0.80〜0.95 の precision/recall を出してください。暫定運用は `>=0.90 hard veto`, `0.82-0.90 warning + pattern validators` の二段階が妥当です。最終判定には max score、matched incident、collection version を Sheets/SQLite に保存してください。

- `generators/objective_scorer.py:70` / `generators/subjective_evaluator.py:40`  
  note では citation_count が non-blocking になっており、accuracy は LLM subjective に寄っています。「事実 vs 主張」の deterministic 判別が弱いため、99.9% ゼロ目標とは噛み合いません。  
  修正パッチ案: `ClaimAuditor` を追加し、数値、日付、固有名詞、比較最上級、人物/組織の発言を fact claim として抽出してください。fact claim は同段落または近傍に citation が無ければ objective C。意見表現は許可しても、断定文は citation 必須にします。

- `generators/chatgpt_image_generator.py:1000` / `generators/chatgpt_image_generator.py:1360` / `generators/chatgpt_image_generator.py:1488` / `generators/chatgpt_batch_helper.py:28`  
  ChatGPT 画像生成は size guard が入っただけで、`_start_new_chat()` の根本修正と重複画像検出が足りません。`_wait_for_image()` が stale last assistant image を拾う余地も残ります。  
  修正パッチ案: 生成ごとに new page で `https://chatgpt.com/?temporary-chat=true` を開き、composer が空で assistant turn が 0 であることを検証してください。失敗時は「新しいチャット」ボタンを英日 selector で click、さらに既存 image src を `skip_urls` に seed する。download 後は `>50KB`, dimensions, MD5 batch uniqueness, OCR/text-presence を通さない限り ChatGPT 成功扱いにせず、即 Pillow に落とすべきです。

- `scripts/build_rag_index.py:204` / `generators/rag_retriever.py:86` / `main.py:764` / `.env.example:42`  
  RAG index は `data/` 配下で gitignored なのに、`.env.example` は `RAG_ENABLED=true` です。新 clone では RAG が有効に見えて、実際は index 欠落で fail-open し得ます。  
  修正パッチ案: 起動 preflight で `RAG_ENABLED=true` かつ index 欠落/manifest 不一致なら `scripts/build_rag_index.py` を自動実行するか、hallucination guard だけ fail-closed にしてください。`rag_index_manifest.json` に source file hash、chunk count、built_at を保存し、ログに必ず出すべきです。

**Medium**

- `generators/objective_scorer.py:601` / `generators/objective_scorer.py:657`  
  word target 2200-3500 と visual B=1 は pass-rate 改善としては分かりますが、cover 品質とは無関係です。visual_count が 1 でも「文字入りサムネ」がある保証はありません。  
  修正パッチ案: `visual_count` と別に `cover_quality` objective を追加してください。`cover_quality` は cover file の存在、local 保存、サイズ、text overlay、title token、重複 MD5 を採点対象にし、note publish では C を blocking にします。

- `main.py:2660` / `main.py:3300`  
  borderline-B regen feedback が旧 4000-5500 前提を残しています。新 target は 2200-3500 なのに、regen が長文化を促すと密度低下とハルシ追加の温床になります。  
  修正パッチ案: default length target を 2200-3500、acceptable floor を 1700 に統一してください。すでに B 範囲の記事は文字数だけで regen しない。regen 理由は `unsupported_claims`, `missing_citations`, `cover_quality` のような安全性指標を優先すべきです。

- `main.py:764` / `main.py:893`  
  `_log_rag_coverage()` は `generation_guides` と `ops_incidents` を検索しますが、Writer prompt には `anti_patterns + successes` しか渡っていません。名前は coverage でも実効は observability です。  
  修正パッチ案: どちらかに寄せてください。Writer に効かせるなら、`generation_guides` は top 2、`ops_incidents` は publish/preflight 用に top 2 を明示注入。効かせないならログ名を `rag_observability` にして、品質保証と混同しないようにするべきです。

- `main.py:3220` / `utils/telemetry_db.py:185`  
  `ab_experiments` の variant が `AB_VARIANT` 未設定なら全て `baseline`、`rag_block_chars=0` 固定です。これでは pass-rate-driven redesign の効果測定が壊れます。  
  修正パッチ案: variant は env ではなく実際の feature flags から自動生成してください。例: `c_rescue_on+rag_hallu_veto092+pillow_off`。`rag_block_chars=len(learned_block)`、generator model、regen reason、cover generator も保存対象にしてください。

- `generators/content_sanitizer.py:73`  
  `_EMPTY_BULLET_SINGLE_RE` は `- メリット:` のような親 bullet を消す可能性があります。直下にネスト bullet がある正常な構造まで削ると、記事の論理構造が壊れます。  
  修正パッチ案: 削除対象を `URL:`, `出典:`, `引用:` など既知 placeholder label に限定するか、次行が blank/heading の場合だけ削除してください。`- メリット:\n  - ...` を保持する regression test を追加してください。

**Low**

- `docs/knowledge/hallucination_registry.md:16`  
  事象 16-19 が「修正済(prompt層)」扱いなのは危険です。prompt-only は mitigation であって fixed ではありません。  
  修正パッチ案: status を `Mitigated: prompt-only / deterministic guard pending` に変更し、対応する sanitizer/Critic test ID を埋められる欄を追加してください。

- `docs/knowledge/ops_incidents.md:10` / `main.py:836`  
  docs では ops incidents を Critic/publisher に渡すように読めますが、実装は startup banner logging です。  
  修正パッチ案: docs を observability と明記するか、publisher preflight に実際に渡してください。特に note UI drift は publish 前 check に効かせるべきです。

- `generators/subjective_evaluator.py:40`  
  prompt 文言は 4 dimensions と言いながら実際は 5 dimensions です。小さいですが、評価器の自己矛盾は避けるべきです。  
  修正パッチ案: 文言を 5 dimensions に直し、schema も固定してください。

**サムネ最終形**

`cover_image` の優先順位は、`validated existing local cover -> ChatGPT generated cover -> Pillow text infographic -> fail publish` が安全です。Unsplash/image_sourcer は cover fallback に使わず、本文 inline 画像専用にしてください。ChatGPT は成功率が不安定なので最優先の品質候補にはできますが、信頼候補にはしない。Pillow を必ず最後の成功経路に置くのが、手動介入なしの現実解です。

**もし 1 つだけ直すなら**

`main.py` の hallu-veto を最終集計に確実に効かせる修正です。今のままだと「検出したのに通す」可能性があり、99.9% ゼロ目標では最も危険です。次点で C-rescue regen の fact ledger 化です。
