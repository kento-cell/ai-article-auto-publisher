"""One-off: reject the off-brand 男性更年期 article, approve the K-beauty
PDRN+NAD+ and 2 zenn arXiv articles. 2026-06-16 routine."""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()
from utils.sheets_manager import SheetsManager

sm = SheetsManager()
pending = sm.get_pending_articles()
print(f"pending count: {len(pending)}")
for p in pending:
    aid = p.get('article_id', '')
    t = (p.get('title') or '')[:64]
    if '男性更年期' in t:
        sm.update_status(aid, '❌却下')
        print(f'  REJECT (off-brand, note主軸=K-beauty/K-cafe): {t}')
    else:
        sm.update_status(aid, '✅承認')
        print(f'  APPROVE: {t}')
