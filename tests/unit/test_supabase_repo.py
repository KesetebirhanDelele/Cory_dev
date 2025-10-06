import os
import json
from unittest.mock import MagicMock
import pytest

from app.repo.supabase_repo import SupabaseRepo, SupabaseRepoConfig
from app.repo.dtos import MessageDTO, EventDTO, LinkRefDTO

def repo_with_mock(session_mock) -> SupabaseRepo:
    cfg = SupabaseRepoConfig(
        base_url="https://example.supabase.co",
        service_key="svc",
        schema="dev_nexus",
        max_attempts=3,
        base_backoff_seconds=0.001,
    )
    r = SupabaseRepo(cfg)
    r._session = session_mock
    return r

class Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body) if body is not None else ""
    def json(self):
        return self._body

def test_log_outbound_idempotent_upsert():
    s = MagicMock()
    # First call 201 (created), second call 200 (merged) with same body
    s.post.side_effect = [
        Resp(201, [{"id": "m1", "provider_ref": "r1", "direction": "outbound"}]),
        Resp(200, [{"id": "m1", "provider_ref": "r1", "direction": "outbound"}]),
    ]
    repo = repo_with_mock(s)

    dto = MessageDTO(provider_ref="r1", direction="outbound", payload={"a": 1})
    first = repo.log_outbound(dto)
    second = repo.log_outbound(dto)

    assert first["id"] == second["id"]
    # Ensure on_conflict was used
    args, kwargs = s.post.call_args
    assert kwargs["params"]["on_conflict"] == "provider_ref,direction"

def test_log_inbound_idempotent_upsert():
    s = MagicMock()
    s.post.return_value = Resp(200, [{"id": "e1", "provider_ref": "r2", "direction": "inbound"}])
    repo = repo_with_mock(s)

    dto = EventDTO(provider_ref="r2", direction="inbound", type="delivered")
    out = repo.log_inbound(dto)

    assert out["id"] == "e1"
    args, kwargs = s.post.call_args
    assert kwargs["params"]["on_conflict"] == "provider_ref,direction"

def test_get_enrollment_status_deterministic():
    s = MagicMock()
    # enrollment -> active
    s.request.side_effect = [
        Resp(200, [{"id": "enr1", "status": "active"}]),  # enrollment
        Resp(200, []),                                    # outcome none
        Resp(200, [{"id": "h1"}]),                        # handoff exists
    ]
    repo = repo_with_mock(s)
    status = repo.get_enrollment_status("enr1")
    assert status.computed == "handoff"

def test_link_ref_to_workflow_uses_event_upsert():
    s = MagicMock()
    s.post.return_value = Resp(200, [{"id": "e2", "type": "link"}])
    repo = repo_with_mock(s)

    dto = LinkRefDTO(provider_ref="r3", workflow_id="wf-123", project_id=None)
    out = repo.link_ref_to_workflow(dto)

    assert out["id"] == "e2"
    # verify it routed through /event (UPSERT)
    path = s.post.call_args[0][0]
    assert path.endswith("/rest/v1/event")
    params = s.post.call_args[1]["params"]
    assert params["on_conflict"] == "provider_ref,direction"

def test_retries_on_500():
    s = MagicMock()
    # Two server errors, then success
    s.request.side_effect = [
        Resp(500, {"err": "boom"}),
        Resp(503, {"err": "busy"}),
        Resp(200, [{"id": "x"}]),
    ]
    repo = repo_with_mock(s)
    out = repo._request("GET", "/rest/v1/message", params={"select": "id"})
    assert out.status_code == 200
