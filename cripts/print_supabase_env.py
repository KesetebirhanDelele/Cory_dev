import os
from dotenv import load_dotenv

load_dotenv()

print("SUPABASE_URL:", os.getenv("SUPABASE_URL"))
print("SUPABASE_SERVICE_KEY set?:", bool(os.getenv("SUPABASE_SERVICE_KEY")))
