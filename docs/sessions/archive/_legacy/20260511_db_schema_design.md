# RAG + telemetry DB 設計 (2026-05-11)

RAG 構築の一部として、現状の DB / store 設計を明文化し、欠けている
piece を埋める。本ドキュメントが新規スプリント着手時の正典。

---

## 0. 全体構造

```
┌───────────────────────────────────────────────────────────────┐
│ Storage tier (3 layers)                                        │
├───────────────────────────────────────────────────────────────┤
│                                                                │
│  1. ChromaDB (semantic / vector store)                        │
│     └─ data/rag_index/chroma.sqlite3 + HNSW bins              │
│        5 collections × 347 chunks                              │
│                                                                │
│  2. JSON store (canonical document store)                     │
│     ├─ data/knowledge_topics.json    (topic pool)             │
│     ├─ data/articles/*.json          (per-article record)     │
│     ├─ data/seen_urls.json           (collection dedup)       │
│     ├─ data/rss_feed_failures.json   (operational state)      │
│     └─ data/knowledge_cooldown.jsonl (topic usage log)        │
│                                                                │
│  3. SQLite (telemetry / time-series) ★ NEW                    │
│     └─ data/telemetry.sqlite3                                  │
│        ├─ engagement_log    (公開後の♥/💬計測)                  │
│        ├─ regen_history     (再生成試行履歴)                     │
│        ├─ ab_experiments    (A/B テスト結果)                    │
│        └─ generation_cost   (LLM / 画像生成コスト trace)         │
└───────────────────────────────────────────────────────────────┘
```

3 層に分ける理由：

- **Layer 1 (ChromaDB)**: ベクトル検索の専門。document 本体 + embedding + metadata の最小単位。
- **Layer 2 (JSON)**: 「正典」の human-readable 形式。grep / 編集できる。Git で管理可能なものは管理 (`data/` は gitignored だが、再構成可能なよう script で管理)。
- **Layer 3 (SQLite)**: append-only / 時系列の telemetry。クエリしやすく、規模が大きくなっても遅くならない。

---

## 1. ChromaDB collections (Layer 1)

各 collection の schema は同一：

```python
{
    "id":        str,          # PK, 例: "hallucinations-0004"
    "embedding": float[768],   # multilingual-e5-base
    "document":  str,          # "passage: " prefix + 本文
    "metadata":  dict,         # 下記参照
}
```

### `anti_patterns` (2 chunks)
- **Source**: `docs/knowledge/quality_anti_patterns.md` (H2 単位)
- **ID 例**: `anti_patterns-0001`
- **Metadata**:
  - `source_file: str` (= `"quality_anti_patterns.md"`)
  - `section_title: str` (= 「避けるべきタイトル型 (下位に集中、上位に出ない)」)
  - `section_index: int` (= 0-based)
  - `category: str` (= collection name)
- **用途**: 生成前 prompt 注入（Sprint 4）

### `successes` (3 chunks)
- **Source**: `docs/knowledge/quality_successes.md`
- 上記と同形式
- **用途**: 生成前 prompt 注入（Sprint 4）

### `hallucinations` (17 chunks)
- **Source**: `docs/knowledge/hallucination_registry.md`
- 上記と同形式
- **用途**: critic agent への semantic 注入（Sprint 2）

### `generation_guides` (70 chunks)
- **Source**: 14 ファイル（image-gen / affiliate / monetization / membership / etc.）
- **ID 採番**: collection 内で cumulative (multi-file collision 回避)
- **用途**: 必要時に operator が CLI 経由で query（auto-injection 無し）

### `past_articles` (255 chunks)
- **Source**: `data/articles/*.json` の title + summary (1記事 = 1 chunk)
- **Metadata**:
  - `source_file: str` (= `"note-Notion_AI__...d359c01b.json"`)
  - `section_title: str` (= 記事タイトル先頭 80 文字)
  - `section_index: int` (ファイル列挙順)
  - `category: str` (= `"past_articles"`)
- **用途**: 重複検出（Sprint 3）

---

## 2. JSON 正典ストア (Layer 2)

### `data/knowledge_topics.json` (42 件)

```typescript
type KnowledgeTopic = {
  id: string;              // PK 例: "ai_010", "kb_001", "hg_002"
                           // prefix で category 識別: ai_/kb_/hg_/cb_/si_/al_/pai_
  category: enum;          // "ai_sidejob" | "k_beauty" | "hidden_gourmet"
                           // | "coffee_barista" | "self_improvement"
                           // | "ai_literacy" | "physical_ai"
  persona: string;
  intent: enum;            // "informational" | "transactional"
  pain: string;
  promise: string;
  outline: string;         // slash-separated section names
  evidence_required: string[];
  affiliate_family: string;
  rotation_weight: number; // sampling weight (default 1.0)
  cooldown_days: number;   // default 30
  prohibited_angles: string[];
  length_target?: {        // 2026-05-11 追加 (optional)
    min: number;
    max: number;
  };
};
```

### `data/articles/<article_id>.json` (255 件)

```typescript
type Article = {
  // --- 識別 ---
  article_id: string;      // PK 例: "note-AI ライティングを-14b5d1c1"
  slug: string;            // file-safe slug
  title: string;
  platform: enum;          // "zenn" | "note"
  source: string;          // 収集元
  url: string;             // 収集元 URL

  // --- 本文 ---
  content: string;         // 完全 markdown
  summary?: string;        // RAG 用要約 (~300字)

  // --- スコア ---
  scores: {
    objective_grade: enum; // "A" | "B" | "C"
    subjective_grade: enum;
    overall_grade: enum;
    numeric_score: number;
    metrics: {
      word_count: { count, grade, ... };
      citation_count: { count, grade, ... };
      visual_count: { count, grade, ... };
      ...
    };
  };

  // --- 由来 ---
  knowledge_topic?: KnowledgeTopic;  // 由来があれば 全 snapshot
  research_brief?: string;           // Codex 由来

  // --- 公開状態 ---
  published_url?: string;
  published_at?: ISO8601;

  // --- 後処理 ---
  images_regenerated_at?: ISO8601;
  regenerated_cover_path?: string;
  regenerated_inline_paths?: string[];
};
```

### `data/knowledge_cooldown.jsonl` (append-only)

```jsonl
{"id": "ai_010", "ts": "2026-05-11T02:22:37Z"}
{"id": "kb_001", "ts": "2026-04-15T08:00:00Z"}
```

cooldown 期間 (`KnowledgeTopic.cooldown_days`) 内のトピックは
sampling 除外される。

### `data/rss_feed_failures.json` (mutable)

```json
{
  "wwdjapan": {
    "streak": 26,
    "last_fail": 1778453636.18,
    "last_error": "403 Client Error: ..."
  }
}
```

streak ≥ 10 で永久隔離 (recent commit `a9c37b8`)。

---

## 3. SQLite telemetry (Layer 3) — 新規提案

`data/telemetry.sqlite3` を新設。append-only / immutable 系のログを
SQLite に置くと:
- 行追加が高速 (JSONL とほぼ同等)
- クエリが SQL で書ける (集計しやすい)
- インデックスで時系列 + WHERE が高速
- 互換性: stdlib `sqlite3` モジュールで追加依存ゼロ

### Table: `engagement_log`

公開記事のエンゲージメントを定期的にスクレイピングしてここに append。

```sql
CREATE TABLE engagement_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id      TEXT    NOT NULL,           -- → articles/*.json
  platform        TEXT    NOT NULL,           -- 'note' | 'zenn'
  url             TEXT    NOT NULL,
  measured_at     TEXT    NOT NULL,           -- ISO8601
  likes           INTEGER DEFAULT 0,
  comments        INTEGER DEFAULT 0,
  views           INTEGER,                    -- nullable, zenn のみ
  scraped_engagement_score REAL,              -- likes + 0.5*comments + 0.1*views
  FOREIGN KEY (article_id) REFERENCES articles(article_id)
);
CREATE INDEX idx_engagement_article ON engagement_log(article_id);
CREATE INDEX idx_engagement_time    ON engagement_log(measured_at);
```

**現状**: `data/article_performance.jsonl` (74 行) を SQLite に移行。

### Table: `regen_history`

各記事の再生成試行を全部記録。

```sql
CREATE TABLE regen_history (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id        TEXT    NOT NULL,
  attempt           INTEGER NOT NULL,         -- 0 = initial, 1+ = regen
  timestamp         TEXT    NOT NULL,
  objective_grade   TEXT,                     -- 'A' | 'B' | 'C'
  subjective_grade  TEXT,
  overall_grade     TEXT,
  numeric_score     REAL,
  trigger_reason    TEXT,                     -- 'thin_content' | 'B_borderline'
                                              -- | 'manual' | 'subjective_C'
  feedback_summary  TEXT,                     -- regen feedback 先頭 200字
  word_count        INTEGER,
  blocking_issues   TEXT,                     -- JSON array
  FOREIGN KEY (article_id) REFERENCES articles(article_id)
);
CREATE INDEX idx_regen_article  ON regen_history(article_id);
CREATE INDEX idx_regen_attempt  ON regen_history(article_id, attempt);
```

**現状**: 不在。記事 JSON に最終スコアだけ保存、試行間の差分は失われている。

### Table: `ab_experiments`

A/B テスト結果（RAG_ENABLED on/off など）。

```sql
CREATE TABLE ab_experiments (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id   TEXT    NOT NULL,           -- 'rag_enabled_2026_05'
  variant         TEXT    NOT NULL,           -- 'treatment' | 'control'
  article_id      TEXT    NOT NULL,
  generated_at    TEXT    NOT NULL,
  -- snapshot of all relevant metrics at generation time
  objective_grade TEXT,
  subjective_grade TEXT,
  overall_grade   TEXT,
  numeric_score   REAL,
  word_count      INTEGER,
  hallucination_warnings_count INTEGER,       -- Sprint 2 hit count
  rag_block_chars INTEGER,                    -- Sprint 4 prompt size
  notes           TEXT,
  FOREIGN KEY (article_id) REFERENCES articles(article_id)
);
CREATE INDEX idx_ab_exp     ON ab_experiments(experiment_id, variant);
CREATE INDEX idx_ab_article ON ab_experiments(article_id);
```

**現状**: 不在。RAG A/B 評価の前提インフラ。

### Table: `generation_cost`

LLM / 画像 API のコスト trace。1 article = 複数 events。

```sql
CREATE TABLE generation_cost (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id      TEXT,                       -- nullable (--learn 等)
  event_type      TEXT NOT NULL,              -- 'gemma_generate' | 'gemma_score'
                                              -- | 'codex_research' | 'chatgpt_image'
                                              -- | 'embedding' | 'claude_api'
  model           TEXT,                       -- 'gemma3:12b' | 'claude-sonnet-4-6'
  timestamp       TEXT NOT NULL,
  duration_ms     INTEGER,
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  cost_usd        REAL,                       -- estimated, nullable for local
  notes           TEXT
);
CREATE INDEX idx_cost_article ON generation_cost(article_id);
CREATE INDEX idx_cost_event   ON generation_cost(event_type, timestamp);
CREATE INDEX idx_cost_time    ON generation_cost(timestamp);
```

**現状**: 不在。コスト最適化の前提情報なし。

---

## 4. cross-reference (FK 相当)

```
KnowledgeTopic.id
   ↓
Article.knowledge_topic.id  (snapshot, immutable copy)
   ↓
engagement_log.article_id
regen_history.article_id
ab_experiments.article_id
generation_cost.article_id (nullable)
```

ChromaDB 側との関係:

```
data/articles/X.json
   ↓ (build_rag_index --rebuild で再生成)
past_articles collection の chunk

docs/knowledge/quality_*.md
   ↓
anti_patterns / successes collection の chunk

docs/knowledge/hallucination_registry.md
   ↓
hallucinations collection
```

正典 = JSON / Markdown。ChromaDB はそれらの index にすぎない。
JSON が消えても md から再構築可能。

---

## 5. ID 採番ルール

| 種類 | 形式 | 例 |
|---|---|---|
| knowledge_topic.id | `<category-prefix>_<3桁シーケンス>` | `ai_010`, `kb_001`, `hg_002` |
| article.article_id | `<platform>-<title slug 30 chars>-<short hash 8>` | `note-Notion_AIで作る-d359c01b` |
| chroma chunk id | `<collection>-<4桁シーケンス>` | `hallucinations-0004`, `past_articles-0254` |
| sqlite row id | AUTOINCREMENT integer | — |

---

## 6. インデックス再構築トリガー

| イベント | 自動？ | 影響 collection |
|---|---|---|
| `docs/knowledge/quality_*.md` 編集 | ❌ 手動 (`build_rag_index`) | anti_patterns, successes |
| `docs/knowledge/hallucination_registry.md` 編集 | ❌ 手動 | hallucinations |
| `data/articles/*.json` 追加 | ❌ 手動 (1日1回程度想定) | past_articles |
| `docs/knowledge/note-trends/*` 編集 | ❌ 手動 | generation_guides |
| `--learn` 完了 | ✅ auto (`RAG_AUTO_REINDEX`) | 全 collection |

将来案: ファイル監視デーモン (`watchdog` で `docs/knowledge/**/*.md` を監視 → 変更検知で auto rebuild)。

---

## 7. versioning

```python
# generators/rag_retriever.py
_INDEX_VERSION = "v1"
```

schema 変更時の versioning ルール：

| 変更内容 | bump |
|---|---|
| embedding モデル変更 (e5-base → e5-large) | **必須** |
| chunk 採番ルール変更 | **必須** |
| metadata field 追加 | optional (後方互換あれば不要) |
| 新 collection 追加 | optional |

bump 時の挙動: retriever が「version 不一致」を検知したら自動 rebuild
(まだ未実装、Sprint 6 候補)。

---

## 8. 物理ストレージ規模見積もり

| Layer | 想定規模 (6 ヶ月後) | ディスク |
|---|---|---|
| ChromaDB | 5000+ chunks | ~50MB |
| JSON articles | 1500+ 記事 | ~15MB |
| SQLite telemetry | 50,000+ rows | ~5MB |
| 画像 | 1500 × 5枚 | ~3GB (PNG) |

SQLite + ChromaDB 合わせて 100MB 程度。VPS / 自宅 PC で問題ない。

---

## 9. 移行計画

新規 SQLite テーブル追加の段階的アプローチ：

### Sprint 6-A: telemetry init + migration
1. `utils/telemetry_db.py` を作成 (sqlite3 init + 4 テーブル CREATE)
2. `data/article_performance.jsonl` → `engagement_log` テーブル移行スクリプト
3. import 時に自動 init (1度きり、idempotent)

### Sprint 6-B: regen_history 配線
1. `_generate_single_article` の各試行で `regen_history` に append
2. 既存 `data/articles/*.json` には冗長保存（後方互換）

### Sprint 6-C: generation_cost 配線
1. `local_llm.py`, `codex client`, `chatgpt_image_generator` の各呼び出し点で append
2. 入出力 token 数を計測（Ollama / Codex / Anthropic SDK のレスポンスから取得）

### Sprint 6-D: ab_experiments 配線
1. `_generate_single_article` で env flag state を読んで variant 判定
2. 結果を append

### Sprint 6-E: 集計クエリ + ダッシュボード
1. `scripts/telemetry_report.py` で日次/週次集計
2. Sheets に push (既存 Sheets 連携を流用)

---

## 10. 開いている疑問点

| # | 質問 | 暫定方針 |
|---|---|---|
| 1 | 古い `*.jsonl` ファイルは消す？ それとも残す？ | engagement だけ SQLite 移行、cooldown jsonl は append-only として残す (シンプル) |
| 2 | SQLite テーブルをすべて作るか、必要なときに作るか？ | 全テーブル CREATE IF NOT EXISTS で起動時に初期化 (idempotent) |
| 3 | telemetry DB のバックアップ戦略は？ | 単一ファイルなので cp で OK。1日 1回 cron バックアップ案 |
| 4 | 月次など期間でのテーブル パーティショニング？ | 50K rows までは不要。1M rows 超えたら年次 archive |
| 5 | ChromaDB のスキーマ migration | データ少ないので rebuild 一択 |

---

## 11. 関連ドキュメント

- `docs/sessions/20260511_rag_requirements.md` — RAG 要件
- `memory/project_rag_migration.md` — point-in-time 状態
- `scripts/build_rag_index.py` — ChromaDB 構築
- `generators/rag_retriever.py` — ChromaDB クエリ

---

更新履歴:
- 2026-05-11 初版（RAG 5 collection + JSON 正典 + SQLite telemetry 提案）
