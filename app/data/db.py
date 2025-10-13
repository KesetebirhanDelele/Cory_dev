# db.py — Supabase version (replaces asyncpg)
from supabase import create_client, Client
from typing import Any, Dict, List
import os
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SCHEMA = os.getenv("SUPABASE_SCHEMA", "dev_nexus")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ---------- Reads ----------

def fetch_due_actions() -> List[Dict[str, Any]]:
    """
    Reads from a view that lists enrollments whose next action is due.
    (You must have 'v_due_actions' defined in your schema)
    """
    response = supabase.table(f"{SCHEMA}_v_due_actions").select("*").execute()
    return response.data or []


def fetch_due_sms() -> List[Dict[str, Any]]:
    """
    Pull planned SMS that are due to send now.
    Equivalent to the asyncpg query you had before.
    """
    response = (
        supabase.table(f"{SCHEMA}_campaign_activity")
        .select("id, org_id, enrollment_id, generated_message")
        .eq("channel", "sms")
        .eq("status", "planned")
        .lte("scheduled_at", "now()")
        .order("scheduled_at", desc=False)
        .execute()
    )
    return response.data or []


# ---------- Writes ----------

def insert_activity(activity: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insert a new activity into campaign_activity.
    Returns inserted record with ID.
    """
    response = supabase.table(f"{SCHEMA}_campaign_activity").insert(activity).execute()
    if not response.data:
        raise RuntimeError("Insert failed")
    return response.data[0]


def update_activity(activity_id: int, patch: Dict[str, Any]) -> None:
    """
    Update activity record by ID.
    """
    if not patch:
        return
    supabase.table(f"{SCHEMA}_campaign_activity").update(patch).eq("id", activity_id).execute()


def upsert_staging(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upsert into phone_call_logs_stg by call_id.
    """
    response = (
        supabase.table(f"{SCHEMA}_phone_call_logs_stg")
        .upsert(row, on_conflict="call_id")
        .execute()
    )
    if not response.data:
        raise RuntimeError("Upsert failed")
    return response.data[0]


# ---------- Example RPC ----------

def rpc_ingest_phone_logs(max_rows: int = 100) -> int:
    """
    Calls a Postgres function via Supabase RPC.
    SELECT dev_nexus.usp_ingestphonecalllogs(p_max_rows := $1);
    """
    response = supabase.rpc("usp_ingestphonecalllogs", {"p_max_rows": max_rows}).execute()
    return int(response.data or 0)
