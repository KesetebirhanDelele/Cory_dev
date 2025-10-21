# tests/integration/test_kpi_endpoints.py
import os
from supabase import create_client

def test_kpi_rpcs_smoke():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    assert isinstance(sb.rpc("rpc_kpi_latency_p95", {}).execute().data, list)
    assert isinstance(sb.rpc("rpc_kpi_deliverability", {}).execute().data, list)
    assert isinstance(sb.rpc("rpc_kpi_response_by_variant", {}).execute().data, list)
