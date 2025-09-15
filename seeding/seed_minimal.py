# seed_minimal_rest.py
from dotenv import load_dotenv; load_dotenv()
import os, uuid
from datetime import datetime, timezone
from supabase import create_client

SCHEMA = "dev_nexus"  # change if yours differs

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
db = sb.postgrest.schema(SCHEMA)

# 1) org
org = db.from_("organizations").select("*").limit(1).execute().data[0]
org_id = org["id"]

# 2) campaign
camp = db.from_("campaigns").insert({
    "id": str(uuid.uuid4()), "org_id": org_id,
    "name": "Test Campaign", "goal_prompt": "Test goal", "campaign_type": "live"
}).execute().data[0]
campaign_id = camp["id"]

# 3) step
step = db.from_("campaign_steps").insert({
    "id": str(uuid.uuid4()), "campaign_id": campaign_id, "order_id": 1,
    "channel": "sms", "wait_before_ms": 0
}).execute().data[0]

# 4) contact
contact = db.from_("contacts").insert({
    "id": str(uuid.uuid4()), "org_id": org_id, "first_name": "Testy",
    "last_name": "McTestface", "phone": "+15555550123"
}).execute().data[0]

# 5) enrollment + 6) planned activity
now = datetime.now(timezone.utc).isoformat()
enrollment = db.from_("campaign_enrollments").insert({
    "id": str(uuid.uuid4()), "org_id": org_id, "contact_id": contact["id"],
    "campaign_id": campaign_id, "status": "active", "started_at": now,
    "current_step_id": step["id"], "next_channel": "sms", "next_run_at": now
}).execute().data[0]

activity = db.from_("campaign_activities").insert({
    "id": str(uuid.uuid4()), "org_id": org_id, "enrollment_id": enrollment["id"],
    "campaign_id": campaign_id, "step_id": step["id"], "channel": "sms",
    "status": "planned", "scheduled_at": now, "generated_message": "Hello from test plan!"
}).execute().data[0]

print("Seeded:", {"enrollment_id": enrollment["id"], "activity_id": activity["id"]})
