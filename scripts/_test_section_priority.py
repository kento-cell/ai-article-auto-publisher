import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
from generators.chatgpt_batch_helper import _select_image_sections, _section_image_priority

sections = [
    ("赤羽がせんべろの聖地になった背景", "b1"),
    ("1軒目: 鯉とうなぎ「まるます家」 - 朝から飲める赤羽の象徴", "b2"),
    ("2軒目: もつ焼き「大昇」 - 焼き場の煙と地元常連の温度感", "b3"),
    ("3軒目: 立ち飲み「いこい本店」 - 戦後から続く立ち飲み文化の原点", "b4"),
    ("4軒目: もつ焼き「まるよし」 - 行列必至の丁寧な仕込み", "b5"),
    ("訪問前のマナー・予算感・心構え", "b6"),
    ("シーン別: 一人飲み / 友人連れ / カップル", "b7"),
    ("まとめ - 赤羽飲み歩きの楽しみ方", "b8"),
    ("ご利用にあたって", "b9"),
]
print("priorities:")
for t, _ in sections:
    print(f"  [{_section_image_priority(t):+4d}] {t}")
print("selected (inline_count=4):")
for t, _ in _select_image_sections(sections, 4):
    print(f"  -> {t}")
