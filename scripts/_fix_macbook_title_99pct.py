"""Emergency one-shot: rewrite MacBook article (nc5d53fdebaf9) title to
remove the deny-pattern phrase '99%の人が知らない' (statistic fabrication).

Original: 【警告】【永久保存版】MacBookにタッチ機能が来る？ 99%の人が知らない開発の裏事情
Fixed:    【警告】【永久保存版】MacBookにタッチ機能が来る？ サプライチェーン情報で見えてきた開発の裏事情
"""
from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
for ln in (_REPO/".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.startswith("#"):
        k,v = ln.split("=",1); os.environ.setdefault(k.strip(), v.strip())
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("fix_title")
from publishers.note_publisher import NotePublisher

NOTE_URL = "https://note.com/kento_kanazawa/n/nc5d53fdebaf9"
NEW_TITLE = "【警告】【永久保存版】MacBookにタッチ機能が来る？ サプライチェーン情報で見えてきた開発の裏事情"

pub = NotePublisher(headless=False)
try:
    ok = pub.edit_article(url=NOTE_URL, new_title=NEW_TITLE)
    log.info("edit_article -> %s", ok)
finally:
    pub.close()
