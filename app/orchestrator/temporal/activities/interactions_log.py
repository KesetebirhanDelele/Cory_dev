from temporalio import activity
from app.data import supabase_repo as repo

@activity.defn
async def log(enrollment_id: str, action: str) -> None:
    """Record a normalized interaction for observability."""
    try:
        await repo.insert_interaction(enrollment_id=enrollment_id, channel=action.replace("send_",""), status="attempted")
    except Exception:
        # keep the workflow resilient; log failure server-side
        pass
