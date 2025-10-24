from openai import OpenAI
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()  # loads .env containing SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENAI_API_KEY

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

rows = supabase.table("documents").select("*").execute().data
print(f"📄 Found {len(rows)} documents to embed...")

for r in rows:
    emb = client.embeddings.create(
        input=r["content"],
        model="text-embedding-3-small"
    ).data[0].embedding
    supabase.table("embeddings").insert({
        "doc_id": r["id"],
        "content": r["content"],
        "embedding": emb
    }).execute()
    print(f"✅ Embedded: {r['title']}")

print("🎉 Embeddings seeding complete.")
