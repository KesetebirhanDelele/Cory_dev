# campaign_builder.py
import uuid
from supabase_repo import sb, SCHEMA  # or use asyncpg from db.py

def create_campaign(org_id: str, name: str, goal: str, campaign_type="live") -> str:
    resp = (sb.postgrest.schema(SCHEMA)
            .from_("campaigns")
            .insert({"id": str(uuid.uuid4()), "org_id": org_id, "name": name,
                     "goal_prompt": goal, "campaign_type": campaign_type})
            .execute())
    return resp.data[0]["id"]

def add_step(campaign_id: str, order_id: int, channel: str,
             wait_before_ms: int, goal_prompt: str | None = None) -> str:
    resp = (sb.postgrest.schema(SCHEMA)
            .from_("campaign_steps")
            .insert({"campaign_id": campaign_id, "order_id": order_id, "channel": channel,
                     "wait_before_ms": wait_before_ms, "goal_prompt": goal_prompt})
            .execute())
    return resp.data[0]["id"]

def upsert_call_policy(campaign_id: str, status: str, end_call_reason: str | None,
                       is_connected: bool, should_retry: bool, retry_sms: bool,
                       retry_after_ms: int | None) -> None:
    (sb.postgrest.schema(SCHEMA)
       .from_("campaign_call_policies")
       .upsert({"campaign_id": campaign_id, "status": status,
                "end_call_reason": end_call_reason,
                "is_connected": is_connected, "should_retry": should_retry,
                "retry_sms": retry_sms, "retry_after_ms": retry_after_ms},
               on_conflict="campaign_id,status,end_call_reason")
       .execute())
