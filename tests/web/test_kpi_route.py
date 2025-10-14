# tests/web/test_kpi_route.py
from fastapi.testclient import TestClient
from app.web.server import app

# --- lightweight stub that mimics supabase client ---
class _Resp:
    def __init__(self, data): self.data = data
class _RPC:
    def __init__(self, name): self.name = name
    def execute(self):
        if self.name == "rpc_kpi_latency_p95":
            return _Resp([{"p95_end_to_end_ms": 123.0}])
        if self.name == "rpc_kpi_deliverability":
            return _Resp([{"channel": "email", "deliverability_pct": 98.5}])
        if self.name == "rpc_kpi_response_by_variant":
            return _Resp([{"variant_id": "A", "response_rate_pct": 12.3}])
        return _Resp([])
class FakeSb:
    def rpc(self, name, _): return _RPC(name)

# Patch the module-level client used by the route
import app.web.routes_kpi as routes_kpi
routes_kpi._sb = FakeSb()

def test_kpi_route_ok():
    c = TestClient(app)
    r = c.get("/api/v1/kpi")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"latency_p95", "deliverability", "response_by_variant"}
    assert isinstance(body["latency_p95"], list)
    assert isinstance(body["deliverability"], list)
    assert isinstance(body["response_by_variant"], list)
