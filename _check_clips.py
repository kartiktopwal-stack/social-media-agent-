from dotenv import load_dotenv
load_dotenv()
from src.core.db import get_connection
conn = get_connection()
rows = conn.execute("SELECT id, niche, status, hook_text, final_path FROM clips ORDER BY id").fetchall()
print(f"Total clips: {len(rows)}")
for r in rows:
    print(f"  #{r['id']}  status={r['status']:<15}  niche={r['niche']}")
    print(f"         hook={r['hook_text']}")
    print(f"         final={r['final_path']}")
conn.close()
