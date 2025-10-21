# db2.py — Test Supabase REST API connection
from supabase import create_client, Client
import os
from dotenv import load_dotenv

def main():
    # Load variables from .env file into environment
    load_dotenv()

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise ValueError("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env or environment.")

    print(f"Using Supabase project: {url}")

    # Initialize Supabase client
    supabase: Client = create_client(url, key)

    # Test query — select first few rows from 'campaign' table
    try:
        response = supabase.table("campaign").select("*").limit(5).execute()
        print("✅ Connection successful!")
        print("Sample data from 'campaign':")
        print(response.data)
    except Exception as e:
        print("❌ Failed to fetch data from Supabase.")
        print("Error:", e)

if __name__ == "__main__":
    main()
