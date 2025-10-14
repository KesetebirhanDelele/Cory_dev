import os
from fastapi import APIRouter
from supabase import create_client

router = APIRouter(prefix="/api/v1/kpi", tags=["kpi"])

# module-level client for simplicity; tests can monkeypatch this
_sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

@router.get("")
def kpis():
    p95  = _sb.rpc("public.rpc_kpi_latency_p95", {}).execute().data if False else _sb.rpc("rpc_kpi_latency_p95", {}).execute().data
    deliv= _sb.rpc("rpc_kpi_deliverability", {}).execute().data
    resp = _sb.rpc("rpc_kpi_response_by_variant", {}).execute().data
    return {"latency_p95": p95, "deliverability": deliv, "response_by_variant": resp}
