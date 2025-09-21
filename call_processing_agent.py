# call_processing_agent.py

from supabase_repo import sb
from datetime import datetime, timezone, timedelta
import os

# -----------------------------
# Schema handling & table helper
# -----------------------------
DEFAULT_SCHEMA = os.getenv("SUPABASE_SCHEMA", "dev_nexus")
ANY = "ANY"

def _schema(sb_client):
    """Prefer the schema pinned on the client; fallback to env; then dev_nexus."""
    try:
        return getattr(sb_client.postgrest, "schema") or DEFAULT_SCHEMA
    except Exception:
        return DEFAULT_SCHEMA

def T(sb_client, table_name: str):
    """Always pass schema explicitly; NEVER qualify the table name string."""
    return sb_client.table(table_name, schema=_schema(sb_client))

# -----------------------------
# Time helper (JSON-safe)
# -----------------------------
def iso(dt):
    """Return an ISO-8601 (UTC) string for PostgREST."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()

# -----------------------------
# Policy helpers / utilities
# -----------------------------
def policy_for(campaign_id, status, reason):
    pol = (
        T(sb, "campaign_call_policies")
        .select("*")
        .eq("campaign_id", campaign_id)
        .in_("status", [status or ANY, ANY])
        .in_("end_call_reason", [reason or ANY, ANY])
        .execute()
        .data
        or []
    )
    if pol:
        pol.sort(
            key=lambda p: (
                0 if p["status"] == (status or ANY) else 1,
                0 if p["end_call_reason"] == (reason or ANY) else 1,
            )
        )
        return pol[0]

    glob = (
        T(sb, "phone_log_decisions")
        .select("*")
        .in_("status", [status or ANY, ANY])
        .in_("end_call_reason", [reason or ANY, ANY])
        .execute()
        .data
        or []
    )
    if glob:
        glob.sort(
            key=lambda d: (
                0 if d["status"] == (status or ANY) else 1,
                0 if d["end_call_reason"] == (reason or ANY) else 1,
            )
        )
        g = glob[0]
        g["first_retry_mins"] = g.get("first_retry_mins") or 1440
        g["next_retry_mins"] = g.get("next_retry_mins") or 1440
        g["max_retry_days"] = g.get("max_retry_days") or 4
        g["align_same_time"] = True if g.get("align_same_time") is None else g.get("align_same_time")
        return g

    # Fallback policy to satisfy retry + SMS follow-up path if nothing is configured
    return {
        "is_connected": False,
        "should_retry": True,
        "retry_sms": True,
        "first_retry_mins": 2,
        "next_retry_mins": 60,
        "max_retry_days": 4,
        "align_same_time": True,
    }

def count_attempts(enrollment_id, step_id):
    # Using exact count from Supabase; .count via select works when enabled on server
    return (
        T(sb, "campaign_activities")
        .select("id", count="exact")
        .eq("enrollment_id", enrollment_id)
        .eq("step_id", step_id)
        .eq("channel", "voice")
        .execute()
        .count
    )

def schedule_sms(enrollment_id, send_at=None, message=None):
    row = {
        "enrollment_id": enrollment_id,
        "channel": "sms",
        "status": "planned",
        "scheduled_at": iso(send_at or datetime.now(timezone.utc)),
    }
    e = (
        T(sb, "campaign_enrollments")
        .select("*")
        .eq("id", enrollment_id)
        .single()
        .execute()
        .data
    )
    row.update(
        {
            "org_id": e["org_id"],
            "campaign_id": e["campaign_id"],
            "step_id": e["current_step_id"],
        }
    )
    T(sb, "campaign_activities").insert(row).execute()

# -----------------------------
# Core processing
# -----------------------------
def process_one(stg):
    enrollment_id = stg.get("enrollment_id")
    if not enrollment_id and stg.get("contact_id"):
        active = (
            T(sb, "campaign_enrollments")
            .select("*")
            .eq("contact_id", stg["contact_id"])
            .eq("status", "active")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not active:
            T(sb, "phone_call_logs_stg").update(
                {
                    "processed": True,
                    "processed_at": iso(datetime.now(timezone.utc)),
                    "error_msg": "no active enrollment",
                }
            ).eq("id", stg["id"]).execute()
            return
        enrollment_id = active[0]["id"]

    e = (
        T(sb, "campaign_enrollments")
        .select("*")
        .eq("id", enrollment_id)
        .single()
        .execute()
        .data
    )
    if not e or e["status"] != "active":
        T(sb, "phone_call_logs_stg").update(
            {
                "processed": True,
                "processed_at": iso(datetime.now(timezone.utc)),
                "error_msg": "not active",
            }
        ).eq("id", stg["id"]).execute()
        return

    # ✅ Ensure enrollment has a valid step
    if not e.get("current_step_id"):
        first = (
            T(sb, "campaign_steps")
            .select("id")
            .eq("campaign_id", e["campaign_id"])
            .order("order_id")
            .limit(1)
            .execute()
            .data
        )
        if first:
            e["current_step_id"] = first[0]["id"]
        else:
            T(sb, "phone_call_logs_stg").update(
                {
                    "processed": True,
                    "processed_at": iso(datetime.now(timezone.utc)),
                    "error_msg": "no steps in campaign",
                }
            ).eq("id", stg["id"]).execute()
            return

    # Log the voice call activity
    act = {
    "org_id": e["org_id"],
    "enrollment_id": e["id"],
    "campaign_id": e["campaign_id"],
    "step_id": e["current_step_id"],
    "attempt_no": 1,
    "channel": "voice",
    # ✅ use the actual call status, not always "completed"
    "status": stg.get("status") or "failed",
    "scheduled_at": iso(stg.get("start_time") or datetime.now(timezone.utc)),
    "sent_at": iso(stg.get("start_time") or datetime.now(timezone.utc)),
    "completed_at": iso(datetime.now(timezone.utc)),
    "outcome": stg.get("status"),
    "end_call_reason": stg.get("end_call_reason"),
    "provider_ref": stg.get("call_id"),
    }
    T(sb, "campaign_activities").insert(act).execute()

    # Apply call policy
    pol = policy_for(e["campaign_id"], stg.get("status"), stg.get("end_call_reason"))

    if not pol["is_connected"] and pol["should_retry"]:
        attempts = count_attempts(e["id"], e["current_step_id"]) or 0
        mins = pol["first_retry_mins"] if attempts <= 1 else pol["next_retry_mins"]
        next_run = datetime.now(timezone.utc) + timedelta(minutes=mins)

        if pol["align_same_time"]:
            first = (
                T(sb, "campaign_activities")
                .select("call_started_at")
                .eq("enrollment_id", e["id"])
                .eq("step_id", e["current_step_id"])
                .eq("channel", "voice")
                .order("call_started_at")
                .limit(1)
                .execute()
                .data
                or []
            )
            if first and first[0].get("call_started_at"):
                t = datetime.fromisoformat(first[0]["call_started_at"].replace("Z", "+00:00"))
                next_run = next_run.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)

        if pol["retry_sms"]:
            # Find the next SMS step in this campaign
            next_sms = (
                T(sb, "campaign_steps")
                .select("*")
                .eq("campaign_id", e["campaign_id"])
                .eq("channel", "sms")
                .order("order_id")
                .limit(1)
                .execute()
                .data
                or []
            )
            if next_sms:
                ns = next_sms[0]
                scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=ns.get("delay_minutes") or 0)

                # Insert SMS activity
                T(sb, "campaign_activities").insert({
                    "org_id": e["org_id"],
                    "enrollment_id": e["id"],
                    "campaign_id": e["campaign_id"],
                    "step_id": ns["id"],
                    "channel": "sms",
                    "status": "planned",
                    "scheduled_at": iso(scheduled_at),
                }).execute()

                # Update enrollment to SMS step
                T(sb, "campaign_enrollments").update({
                    "current_step_id": ns["id"],
                    "next_channel": "sms",
                    "next_run_at": iso(scheduled_at),
                    "updated_at": iso(datetime.now(timezone.utc)),
                }).eq("id", e["id"]).execute()

        else:
            # Normal voice retry
            T(sb, "campaign_enrollments").update({
                "next_channel": "voice",
                "next_run_at": iso(next_run),
                "updated_at": iso(datetime.now(timezone.utc)),
            }).eq("id", e["id"]).execute()

        # Always mark staging row processed here
        T(sb, "phone_call_logs_stg").update(
            {"processed": True, "processed_at": iso(datetime.now(timezone.utc)), "error_msg": None}
        ).eq("id", stg["id"]).execute()

        return

    # … existing logic for classification & advancing steps …

    cl = stg.get("classification") or "followup"
    if cl in ("booked", "appointment_booked", "cold", "not_interested", "dnc"):
        T(sb, "campaign_enrollments").update(
            {
                "status": "completed",
                "ended_at": iso(datetime.now(timezone.utc)),
                "current_step_id": None,
                "next_channel": None,
                "next_run_at": None,
                "updated_at": iso(datetime.now(timezone.utc)),
            }
        ).eq("id", e["id"]).execute()
    else:
        # Advance to next step if any (note: column name might be order_index in your schema)
        current_order = (
            T(sb, "campaign_steps")
            .select("order_id")  # adjust to "order_index" if needed by your schema
            .eq("id", e["current_step_id"])
            .single()
            .execute()
            .data["order_id"]
        )
        next_step = (
            T(sb, "campaign_steps")
            .select("*")
            .eq("campaign_id", e["campaign_id"])
            .gt("order_id", current_order)
            .order("order_id")
            .limit(1)
            .execute()
            .data
            or []
        )
        if not next_step:
            T(sb, "campaign_enrollments").update(
                {
                    "status": "completed",
                    "ended_at": iso(datetime.now(timezone.utc)),
                    "current_step_id": None,
                    "next_channel": None,
                    "next_run_at": None,
                    "updated_at": iso(datetime.now(timezone.utc)),
                }
            ).eq("id", e["id"]).execute()
        else:
            ns = next_step[0]
            wait_ms = ns.get("wait_before_ms") or 0
            delta = timedelta(milliseconds=wait_ms)
            T(sb, "campaign_enrollments").update(
                {
                    "current_step_id": ns["id"],
                    "next_channel": ns["channel"],
                    "next_run_at": iso(datetime.now(timezone.utc) + delta),
                    "updated_at": iso(datetime.now(timezone.utc)),
                }
            ).eq("id", e["id"]).execute()

    T(sb, "phone_call_logs_stg").update(
        {"processed": True, "processed_at": iso(datetime.now(timezone.utc)), "error_msg": None}
    ).eq("id", stg["id"]).execute()

# -----------------------------
# Entry point (single pass)
# -----------------------------
async def run_call_processing_once():
    rows = (
        T(sb, "phone_call_logs_stg")
        .select("*")
        .eq("processed", False)
        .order("id")           # earliest first
        .limit(5)
        .execute()
        .data
        or []
    )

    for r in rows:
        try:
            process_one(r)
        except Exception as ex:
            T(sb, "phone_call_logs_stg").update(
                {
                    "processed": True,
                    "processed_at": iso(datetime.now(timezone.utc)),
                    "error_msg": str(ex),
                }
            ).eq("id", r["id"]).execute()
