# supabase_repo.py
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SCHEMA = "dev_nexus"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def fetch_due_sms_via_supabase() -> List[Dict[str, Any]]:
    """
    Reads planned SMS due now from the view.
    Make sure 'dev_nexus' is exposed in API settings, or use service role key.
    """
    resp = (
        sb.postgrest.schema(SCHEMA)
          .from_("v_due_sms_followups")
          .select("*")
          .lte("scheduled_at", _now_iso())
          .execute()
    )
    return resp.data or []

def update_activity_via_supabase(activity_id: str, patch: Dict[str, Any]) -> None:
    """
    Partial update of campaign_activities by id.
    """
    if not patch:
        return
    (
        sb.postgrest.schema(SCHEMA)
          .from_("campaign_activities")
          .update(patch)
          .eq("id", activity_id)
          .execute()
    )

def rpc_ingest_phone_logs(max_rows: int = 100) -> int:
    """
    Calls Postgres function dev_nexus.usp_IngestPhoneCallLogs via RPC.
    """
    # Supabase RPC names don’t include the schema in the name; pass it in the call string.
    res = sb.rpc("dev_nexus.usp_ingestphonecalllogs", {"p_max_rows": max_rows}).execute()
    # Supabase returns {"data": <value>} for scalar returns
    return int(res.data) if res.data is not None else 0
