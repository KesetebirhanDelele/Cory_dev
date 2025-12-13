# scripts/print_supabase_env.py

import os
import sys
from dotenv import load_dotenv

# Ensure project root is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Load .env from project root
load_dotenv()

print("SUPABASE_URL:", os.getenv("SUPABASE_URL"))
print("SUPABASE_SERVICE_KEY set?:", bool(os.getenv("SUPABASE_SERVICE_KEY")))
print("DATABASE_URL:", os.getenv("DATABASE_URL"))
