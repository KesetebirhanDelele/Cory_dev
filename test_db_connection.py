# test_supabase_connection.py
from app.data.db import fetch_due_actions  # Use relative import if "db.py" is in the same folder

try:
    data = fetch_due_actions()
    print("✅ Supabase connection OK")
    print(f"Fetched {len(data)} rows")
except Exception as e:
    print(f"❌ Supabase connection failed: {e}")
