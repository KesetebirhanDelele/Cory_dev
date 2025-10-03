# app/data/supabase_repo.py
import os, time
from supabase import create_client, Client
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SCHEMA = os.getenv("SUPABASE_SCHEMA", "dev_nexus")

sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
db = sb.postgrest.schema(SCHEMA)

class TransientError(Exception): pass  # optionally map HTTP 429/5xx to this

@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.2, min=0.2, max=5),
    retry=retry_if_exception_type(TransientError),
)
def rpc(name: str, payload: dict | None = None):
    res = db.rpc(name, payload or {}).execute()
    # Map rate-limit/5xx to transient for retry (pseudo-check below; adapt to client’s error shape)
    # if res.status_code in (429, 500, 502, 503, 504): raise TransientError()
    return res.data
