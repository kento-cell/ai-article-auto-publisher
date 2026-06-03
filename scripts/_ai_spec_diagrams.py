"""PIL-drawn diagrams for the AI technical spec workbook.

No external deps beyond Pillow (already used by the project's banner
generator). Renders Japanese via Meiryo. generate_all(outdir) returns an
ordered list of (sheet_name, title, png_path) for the workbook builder.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_REG = "C:/Windows/Fonts/meiryo.ttc"
_BLD = "C:/Windows/Fonts/YuGothB.ttc"

# palette (RGB)
NAVY = (31, 56, 100)
BLUE = (46, 83, 149)
LIGHT = (217, 225, 242)
PALEBLUE = (235, 240, 250)
GREEN = (84, 130, 53)
PALEGREEN = (226, 239, 218)
ACCENT = (197, 90, 17)
PALEORANGE = (252, 228, 214)
RED = (192, 0, 0)
PALERED = (248, 215, 211)
GREY = (110, 110, 110)
DARK = (28, 28, 28)
WHITE = (255, 255, 255)

_fcache: dict[tuple, ImageFont.FreeTypeFont] = {}


def font(sz: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (sz, bold)
    if key not in _fcache:
        _fcache[key] = ImageFont.truetype(_BLD if bold else _REG, sz)
    return _fcache[key]


def _wrap(d, text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if d.textlength(cur + ch, font=fnt) <= max_w or not cur:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def _ctext(d, x, y, w, h, text, fnt, color):
    lines = _wrap(d, text, fnt, w - 14)
    asc, desc = fnt.getmetrics()
    lh = asc + desc + 3
    total = lh * len(lines)
    cy = y + (h - total) / 2
    for ln in lines:
        lw = d.textlength(ln, font=fnt)
        d.text((x + (w - lw) / 2, cy), ln, font=fnt, fill=color)
        cy += lh


def box(d, x, y, w, h, text, fill=LIGHT, fsize=21, tcolor=DARK,
        outline=BLUE, bold=False, radius=12, ow=2):
    d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill,
                        outline=outline, width=ow)
    _ctext(d, x, y, w, h, text, font(fsize, bold), tcolor)
    return {"t": (x + w / 2, y), "b": (x + w / 2, y + h),
            "l": (x, y + h / 2), "r": (x + w, y + h / 2),
            "c": (x + w / 2, y + h / 2), "rect": (x, y, w, h)}


def diamond(d, cx, cy, w, h, text, fill=PALEORANGE, outline=ACCENT,
            fsize=18, tcolor=DARK):
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2),
           (cx - w / 2, cy)]
    d.polygon(pts, fill=fill, outline=outline)
    d.line(pts + [pts[0]], fill=outline, width=2)
    _ctext(d, cx - w / 2, cy - h / 2, w, h, text, font(fsize), tcolor)
    return {"t": (cx, cy - h / 2), "b": (cx, cy + h / 2),
            "l": (cx - w / 2, cy), "r": (cx + w / 2, cy), "c": (cx, cy)}


def arrow(d, p1, p2, color=(90, 90, 90), width=3, label=None,
          lcolor=ACCENT, lfsize=17, ldx=8, ldy=-10):
    d.line([p1, p2], fill=color, width=width)
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    L = 13
    for a in (ang - 0.42, ang + 0.42):
        d.line([p2, (p2[0] - L * math.cos(a), p2[1] - L * math.sin(a))],
               fill=color, width=width)
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        d.text((mx + ldx, my + ldy), label, font=font(lfsize, True),
               fill=lcolor)


def elbow(d, p1, p2, color=(90, 90, 90), width=3, label=None, via_x=None):
    """Right-angle connector p1->(corner)->p2 with arrowhead at p2."""
    vx = via_x if via_x is not None else p2[0]
    mid = (vx, p1[1])
    d.line([p1, mid], fill=color, width=width)
    d.line([mid, (vx, p2[1])], fill=color, width=width)
    arrow(d, (vx, p2[1]), p2, color=color, width=width)
    if label:
        d.text((vx + 8, (p1[1] + p2[1]) / 2 - 10), label,
               font=font(16, True), fill=ACCENT)


def canvas(w, h, title):
    im = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 46], fill=NAVY)
    d.text((20, 8), title, font=font(24, True), fill=WHITE)
    return im, d


# ===================================================================== #


def d_architecture(p):
    W, H = 1480, 940
    im, d = canvas(W, H, "図1  全体アーキテクチャ (レイヤ構成)")
    # layer band labels
    bands = [
        (70, "① 収集層", PALEGREEN, GREEN),
        (230, "② 生成・評価層 (AI中核)", LIGHT, BLUE),
        (560, "③ 画像層", PALEORANGE, ACCENT),
        (700, "④ 投稿層", PALEBLUE, BLUE),
    ]
    for y, lab, fill, oc in bands:
        d.text((20, y - 26), lab, font=font(19, True), fill=oc)
    # ① collectors
    cols = ["arXiv", "RSS\n(日/韓)", "Reddit", "Bluesky", "Google\nTrends",
            "knowledge\n_topics"]
    cw, gap, x0 = 205, 16, 40
    boxes1 = []
    for i, c in enumerate(cols):
        boxes1.append(box(d, x0 + i * (cw + gap), 70, cw, 90, c,
                          fill=PALEGREEN, outline=GREEN, fsize=19))
    # ② generation/eval
    box(d, 40, 240, 360, 150,
        "トレンドスコア → 構成パターン選択\n→ LLM生成 (Gemma4:e4b / Ollama)\n→ サニタイザ",
        fill=LIGHT, fsize=19)
    box(d, 430, 240, 300, 150,
        "RAG\nmultilingual-e5-base\n+ chromadb (7 collection)",
        fill=(214, 220, 240), fsize=19)
    box(d, 760, 240, 680, 150,
        "スコアリング\n客観(足切り 9指標) → 主観(LLM 5次元)\n→ 集約 総合=min(客観最低, 主観平均)\nC は自動却下",
        fill=LIGHT, fsize=19)
    # ③ image
    box(d, 40, 560, 690, 90,
        "ChatGPT 画像ツール (Brave CDP:9222) → vision-eval(≥6)\n→ fallback: Pollinations / Unsplash",
        fill=PALEORANGE, outline=ACCENT, fsize=19)
    box(d, 760, 560, 680, 90, "視覚要素を本文へ (cover + inline, note CDN re-host)",
        fill=PALEORANGE, outline=ACCENT, fsize=19)
    # ④ publish
    box(d, 40, 700, 430, 90, "Zenn  (git push / Scrap)", fill=PALEBLUE, fsize=20)
    box(d, 500, 700, 430, 90, "note  (Selenium投稿 + 価格決定)", fill=PALEBLUE, fsize=20)
    box(d, 960, 700, 480, 90, "通知: Slack + Gmail", fill=PALEBLUE, fsize=20)
    # data stores (right side)
    box(d, 40, 840, 680, 70, "データストア: ArticleStore (data/articles/*.json)",
        fill=(238, 238, 238), outline=GREY, fsize=19)
    box(d, 760, 840, 680, 70, "承認台帳: Google Sheets (承認待ち → 承認 → 投稿済み)",
        fill=(238, 238, 238), outline=GREY, fsize=19)
    # vertical flow arrows
    arrow(d, (W / 2, 165), (W / 2, 235))
    arrow(d, (W / 2, 395), (W / 2, 555))
    arrow(d, (W / 2, 655), (W / 2, 695))
    arrow(d, (W / 2, 795), (W / 2, 835))
    im.save(p)
    return p


def d_pipeline(p):
    W, H = 900, 1460
    im, d = canvas(W, H, "図2  処理パイプライン フロー")
    steps = [
        ("収集 (arXiv/RSS/Reddit/Bluesky/Trends/knowledge)", PALEGREEN, GREEN),
        ("トレンドスコア (0-100 ランク付け)", LIGHT, BLUE),
        ("構成パターン選択 (8テンプレ)", LIGHT, BLUE),
        ("LLM記事生成 (Gemma4:e4b)", LIGHT, BLUE),
        ("サニタイズ (placeholder/AI開示除去)", LIGHT, BLUE),
        ("画像生成 (ChatGPT + vision-eval)", PALEORANGE, ACCENT),
        ("客観スコア (足切り 9指標)", LIGHT, BLUE),
        ("主観スコア (LLM 5次元)", LIGHT, BLUE),
        ("集約判定 総合=min(客観最低,主観平均)", LIGHT, BLUE),
    ]
    x, w, h = 200, 500, 70
    y, sp = 62, 104
    prev = None
    for txt, fill, oc in steps:
        b = box(d, x, y, w, h, txt, fill=fill, outline=oc, fsize=19)
        if prev:
            arrow(d, prev["b"], b["t"])
        prev = b
        y += sp
    # decision: C?
    dy = y + 4
    dec = diamond(d, x + w / 2, dy + 55, 300, 110, "総合 C ?", fsize=20)
    arrow(d, prev["b"], dec["t"])
    rej = box(d, x + w + 70, dy + 15, 180, 80, "自動却下\n(NG)", fill=PALERED,
              outline=RED, fsize=19, bold=True)
    arrow(d, dec["r"], rej["l"], label="Yes")
    # no -> sheets
    sh = box(d, x, dy + 150, w, 70, "Sheets 承認待ち + ArticleStore + Gmail通知",
             fill=(238, 238, 238), outline=GREY, fsize=18)
    arrow(d, dec["b"], sh["t"], label="No")
    appr = box(d, x, dy + 270, w, 62, "人間が承認", fill=PALEGREEN,
               outline=GREEN, fsize=20, bold=True)
    arrow(d, sh["b"], appr["t"])
    pub = box(d, x, dy + 382, w, 62, "publish (Phase4)", fill=PALEBLUE,
              outline=BLUE, fsize=20, bold=True)
    arrow(d, appr["b"], pub["t"])
    im.save(p)
    return p


def d_scoring(p):
    W, H = 1380, 900
    im, d = canvas(W, H, "図3  スコアリング判定フロー")
    a = box(d, 60, 80, 300, 80, "客観スコア\n(規則ベース 9指標)", fsize=20)
    dec1 = diamond(d, 600, 120, 260, 110, "客観 C あり?", fsize=19)
    arrow(d, a["r"], dec1["l"])
    rej1 = box(d, 1050, 80, 260, 80, "自動却下", fill=PALERED, outline=RED,
               bold=True, fsize=20)
    arrow(d, dec1["r"], rej1["l"], label="Yes")
    b = box(d, 470, 270, 260, 80, "主観スコア\n(LLM 5次元)", fsize=20)
    arrow(d, dec1["b"], b["t"], label="No")
    dec2 = diamond(d, 600, 440, 320, 120, "title_fulfillment\n= C ?", fsize=18)
    arrow(d, b["b"], dec2["t"])
    arrow(d, dec2["r"], (1050, 440), label="Yes")
    box(d, 1050, 400, 260, 80, "却下\n(タイトル負け)", fill=PALERED,
        outline=RED, bold=True, fsize=19)
    agg = box(d, 420, 610, 360, 90,
              "総合 = min(客観最低, 主観平均)\nnumeric = 0.5×客観 + 0.5×主観",
              fill=LIGHT, fsize=18)
    arrow(d, dec2["b"], agg["t"], label="No")
    # platform branch
    zenn = box(d, 80, 770, 540, 90,
               "Zenn: numeric ≥ 77.5 → 記事(git push) / 未満 → Scrap",
               fill=PALEBLUE, outline=BLUE, fsize=18)
    note = box(d, 700, 770, 600, 90,
               "note: determine_price(grade×evidence)\nA+A¥1980 / A¥980 / B+A¥500 / B¥300 / 他¥200",
               fill=PALEBLUE, outline=BLUE, fsize=17)
    arrow(d, (agg["b"][0] - 120, agg["b"][1]), zenn["t"])
    arrow(d, (agg["b"][0] + 120, agg["b"][1]), note["t"])
    # legend
    d.text((60, 250), "※ 客観Cが1つでもあれば総合C。タイトル負けは即却下。",
           font=font(16, True), fill=GREY)
    im.save(p)
    return p


def d_agents(p):
    W, H = 1340, 820
    im, d = canvas(W, H, "図4  5エージェント議論ループ (会議型)")
    res = box(d, 60, 330, 240, 120,
              "Researcher\n調査・事実確認\n(信頼性の土台)", fill=PALEGREEN,
              outline=GREEN, fsize=19, bold=True)
    coord = box(d, 540, 60, 280, 90, "Coordinator\n進行・収束判断・集約",
                fill=NAVY, tcolor=WHITE, outline=NAVY, fsize=20, bold=True)
    strat = box(d, 430, 250, 220, 110, "Strategist\n差別化角度\n構成提案",
                fsize=19)
    writer = box(d, 720, 250, 220, 110, "Writer\nドラフト執筆", fsize=19)
    critic = box(d, 720, 470, 220, 110, "Critic\n否定起点で照合", fill=PALEORANGE,
                 outline=ACCENT, fsize=19, bold=True)
    # arrows
    arrow(d, res["r"], strat["l"], label="verified_facts")
    arrow(d, strat["r"], writer["l"])
    arrow(d, writer["b"], critic["t"])
    # Writer<->Critic loop
    arrow(d, critic["l"], (writer["l"][0] - 0, writer["b"][1] + 30),
          color=ACCENT, label="指摘→改訂")
    d.text((430, 600), "Writer ↔ Critic は最大2round (例外3)。Critic は肯定せず"
           "『指摘なし=収束可』のみ。", font=font(16, True), fill=GREY)
    # coordinator orchestrates
    for b in (strat, writer, critic):
        d.line([coord["b"], (b["c"][0], b["t"][1])], fill=(180, 180, 180),
               width=1)
    out = box(d, 1010, 350, 270, 110,
              "収束 → Sheets行生成\n(証拠Lv/総合/各次元)", fill=(238, 238, 238),
              outline=GREY, fsize=18)
    arrow(d, critic["r"], out["l"])
    # convergence box
    box(d, 60, 560, 330, 180,
        "収束条件 (全て満たす):\n・Critic未解消 = 0\n・客観C なし\n・未検証主張 なし\n"
        "・証拠Lv B 以上", fill=PALEGREEN, outline=GREEN, fsize=17)
    im.save(p)
    return p


def d_image(p):
    W, H = 1400, 760
    im, d = canvas(W, H, "図5  画像生成カスケード + vision-eval ループ")
    vp = box(d, 50, 90, 250, 100, "visual_prompt_builder\n(Gemma 日本語要約)",
             fsize=18)
    cg = box(d, 360, 90, 300, 100,
             "ChatGPT 画像ツール\n(Brave CDP:9222, 画像毎に new chat)",
             fill=PALEORANGE, outline=ACCENT, fsize=18)
    arrow(d, vp["r"], cg["l"])
    dec = diamond(d, 850, 140, 270, 120, "vision-eval\nSCORE ≥ 6 ?", fsize=18)
    arrow(d, cg["r"], dec["l"])
    ok = box(d, 1110, 90, 240, 100, "採用\n→ soft-delete\n(sidebar掃除)",
             fill=PALEGREEN, outline=GREEN, fsize=18, bold=True)
    arrow(d, dec["r"], ok["l"], label="Yes")
    # retry loop
    retry = box(d, 360, 290, 300, 80, "再生成 (1回まで)", fill=PALERED,
                outline=RED, fsize=18)
    arrow(d, dec["b"], retry["r"], label="No")
    arrow(d, retry["t"], cg["b"], color=RED)
    # fallback chain
    fb1 = box(d, 360, 430, 300, 80, "Pollinations flux\n(USE_POLLINATIONS時)",
              fill=(238, 238, 238), outline=GREY, fsize=17)
    fb2 = box(d, 760, 430, 300, 80, "Unsplash / Pexels (CC0系)",
              fill=(238, 238, 238), outline=GREY, fsize=18)
    arrow(d, retry["b"], fb1["t"], label="なお失敗")
    arrow(d, fb1["r"], fb2["l"])
    d.text((50, 560),
           "・最小10,000byte / MD5重複(プレースホルダ)は全無効化\n"
           "・既定スタイル: 宮崎駿/新海誠/細田守風 水彩 (cover=インフォグラフィック)\n"
           "・style_preset=kbeauty_poster で韓国美容雑誌 実写調",
           font=font(17, True), fill=GREY)
    im.save(p)
    return p


def d_rag(p):
    W, H = 1380, 760
    im, d = canvas(W, H, "図6  RAG構成 (索引と検索)")
    d.text((40, 64), "【索引側】 build_rag_index.py", font=font(19, True),
           fill=GREEN)
    src = box(d, 40, 90, 300, 110,
              "docs/knowledge\nregistries / 戦略md\npast_articles", fill=PALEGREEN,
              outline=GREEN, fsize=18)
    emb = box(d, 420, 95, 260, 100, "multilingual-e5-base\n(passage: 接頭辞)",
              fill=LIGHT, fsize=18)
    arrow(d, src["r"], emb["l"])
    db = box(d, 770, 60, 560, 170,
             "chromadb (data/rag_index/) — 7 collections:\nanti_patterns / successes / "
             "hallucinations / ops_incidents /\ngeneration_guides / past_articles / thumbnail_styles",
             fill=(214, 220, 240), outline=BLUE, fsize=17)
    arrow(d, emb["r"], db["l"])
    d.text((40, 320), "【検索側】 rag_retriever.py (query: 接頭辞)",
           font=font(19, True), fill=ACCENT)
    q = box(d, 770, 320, 560, 90, "e5 検索 (cosine) ± reranker", fill=PALEORANGE,
            outline=ACCENT, fsize=18)
    arrow(d, db["b"], q["t"])
    uses = [
        ("生成ヒント\nanti/successes 閾値0.55", PALEBLUE),
        ("ハルシ ガード\nhallucinations 閾値0.85", PALERED),
        ("重複検出\npast_articles", (238, 238, 238)),
        ("ops バナー\nops_incidents", (238, 238, 238)),
    ]
    bw, gap, x0 = 310, 20, 40
    for i, (txt, fill) in enumerate(uses):
        u = box(d, x0 + i * (bw + gap), 470, bw, 100, txt, fill=fill,
                outline=BLUE if fill != PALERED else RED, fsize=18)
        arrow(d, (q["b"][0], q["b"][1]), u["t"], color=(150, 150, 150))
    d.text((40, 610), "RAG_ENABLED=true (本番ON) / HF_HUB_OFFLINE=1。"
           "新事象は ops_incidents.md 追記→再ingest。", font=font(17, True),
           fill=GREY)
    im.save(p)
    return p


def d_publish(p):
    W, H = 1420, 860
    im, d = canvas(W, H, "図7  publish 分岐 (Phase4)")
    s = box(d, 560, 70, 300, 70, "Sheets 承認済みを取得", fill=PALEGREEN,
            outline=GREEN, fsize=19, bold=True)
    g = box(d, 470, 180, 480, 90,
            "ガード: cadence cap(note 1本/日) / 重複id / publish deny\n(hitは却下)",
            fill=PALEORANGE, outline=ACCENT, fsize=18)
    arrow(d, s["b"], g["t"])
    dec = diamond(d, 710, 340, 240, 100, "platform ?", fsize=19)
    arrow(d, g["b"], dec["t"])
    # zenn branch
    zdec = diamond(d, 280, 470, 260, 110, "numeric ≥ 77.5 ?", fsize=18)
    arrow(d, dec["l"], zdec["t"], label="zenn")
    zart = box(d, 60, 640, 210, 80, "記事 (git push)", fill=PALEBLUE, fsize=18)
    zscr = box(d, 320, 640, 210, 80, "Zenn Scrap", fill=(238, 238, 238),
               outline=GREY, fsize=18)
    arrow(d, zdec["b"], zart["t"], label="Yes")
    arrow(d, zdec["r"], zscr["t"], label="No/404")
    # note branch
    ndec = diamond(d, 1110, 470, 280, 110, "借用画像\nあり?", fsize=17)
    arrow(d, dec["r"], ndec["t"], label="note")
    nfree = box(d, 900, 640, 200, 80, "¥0 強制", fill=PALERED, outline=RED,
                fsize=18)
    npaid = box(d, 1140, 640, 270, 80,
                "determine_price\n¥1980〜¥200", fill=PALEBLUE, fsize=17)
    arrow(d, ndec["l"], nfree["t"], label="Yes")
    arrow(d, ndec["b"], npaid["t"], label="No")
    fin = box(d, 470, 770, 480, 60,
              "投稿 → Slack/Gmail通知 → Sheets 投稿済みに更新",
              fill=(238, 238, 238), outline=GREY, fsize=18)
    arrow(d, (zart["b"][0], zart["b"][1]), fin["l"], color=(170, 170, 170))
    arrow(d, (npaid["b"][0], npaid["b"][1]), fin["r"], color=(170, 170, 170))
    im.save(p)
    return p


def generate_all(outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    specs = [
        ("図1_全体図", "全体アーキテクチャ", d_architecture),
        ("図2_パイプライン図", "処理パイプライン", d_pipeline),
        ("図3_スコアリング図", "スコアリング判定", d_scoring),
        ("図4_エージェント図", "エージェント議論", d_agents),
        ("図5_画像生成図", "画像生成カスケード", d_image),
        ("図6_RAG図", "RAG構成", d_rag),
        ("図7_publish図", "publish分岐", d_publish),
    ]
    out = []
    for name, title, fn in specs:
        png = outdir / f"{name}.png"
        fn(png)
        out.append((name, title, png))
    return out


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent / "docs" / "_spec_assets"
    for n, t, p in generate_all(base):
        print("rendered", p)
