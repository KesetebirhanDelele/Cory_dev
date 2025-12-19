from supabase import create_client, Client
import os

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_due_enrollments(client: Client):
    response = client.table("campaign_enrollments")\
        .select("*")\
        .lte("next_run_at", "now()")\
        .eq("status", "pending")\
        .execute()
    return response.data

def insert_interaction(client: Client, record: dict):
    return client.table("interactions").insert(record).execute()

def update_enrollment_progress(client: Client, enrollment_id: str, next_run_at: str, step_index: int):
    return client.table("campaign_enrollments").update({
        "step_index": step_index,
        "next_run_at": next_run_at
    }).eq("id", enrollment_id).execute()
