from __future__ import annotations
import os, time, json
from typing import Any, Dict, Optional, Sequence, Tuple
import requests
from pydantic import BaseModel, ValidationError

from .dtos import MessageDTO, EventDTO, LinkRefDTO, EnrollmentStatusDTO

DEFAULT_TIMEOUT = 20
RETRYABLE = (408, 429, 500, 502, 503, 504)

class SupabaseRepoConfig(BaseModel):
    base_url: str
    service_key: str
    schema: str = "dev_nexus"
    timeout_seconds: int = DEFAULT_TIMEOUT
    max_attempts: int = 4
    base_backoff_seconds: float = 0.25  # 250ms → ~2s

    @classmethod
    def from_env(cls) -> "SupabaseRepoConfig":
        url = os.environ["SUPABASE_URL"].rstrip("/")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        schema = os.environ.get("DB_SCHEMA", "dev_nexus")
        return cls(base_url=url, service_key=key, schema=schema)

class SupabaseRepo:
    """
    Thin HTTP repo against PostgREST with:
    - Idempotent UPSERTs using on_conflict=(provider_ref,direction)
    - Exponential backoff for retryable HTTP statuses
    """

    def __init__(self, cfg: Optional[SupabaseRepoConfig] = None):
        self.cfg = cfg or SupabaseRepoConfig.from_env()
        self._session = requests.Session()
        self._common_headers = {
            "apikey": self.cfg.service_key,
            "Authorization": f"Bearer {self.cfg.service_key}",
            # Tell PostgREST which DB schema we target
            "Accept-Profile": self.cfg.schema,
            "Content-Type": "application/json",
        }

    # -------------------- internal helpers --------------------

    def _backoff_sleep(self, attempt: int):
        # attempt: 1..N
        delay = self.cfg.base_backoff_seconds * (2 ** (attempt - 1))
        time.sleep(delay)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        expected: Sequence[int] = (200, 201, 204),
    ) -> requests.Response:
        url = f"{self.cfg.base_url}{path}"
        for attempt in range(1, self.cfg.max_attempts + 1):
            resp = self._session.request(
                method,
                url,
                headers=self._common_headers,
                params=params,
                json=json_body,
                timeout=self.cfg.timeout_seconds,
            )
            # Success?
            if resp.status_code in expected:
                return resp
            # Retry?
            if resp.status_code in RETRYABLE and attempt < self.cfg.max_attempts:
                self._backoff_sleep(attempt)
                continue
            # Fail
            raise RuntimeError(
                f"HTTP {resp.status_code} {method} {url} params={params} body={json_body} resp={resp.text}"
            )
        # Should never get here
        raise RuntimeError("unreachable")

    # -------------------- public APIs --------------------

    def log_outbound(self, msg: MessageDTO) -> Dict[str, Any]:
        """
        Idempotent UPSERT into dev_nexus.message using (provider_ref, direction).
        """
        body = msg.model_dump(exclude_none=True)
        # PostgREST upsert: POST + Prefer: resolution=merge-duplicates + on_conflict
        headers = {**self._common_headers, "Prefer": "return=representation,resolution=merge-duplicates"}
        path = "/rest/v1/message"
        params = {"on_conflict": "provider_ref,direction"}
        resp = self._session.post(
            f"{self.cfg.base_url}{path}",
            headers=headers,
            params=params,
            json=body,
            timeout=self.cfg.timeout_seconds,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return data[0] if isinstance(data, list) and data else data
        if resp.status_code in RETRYABLE:
            # one-shot retry loop using the common method (keeps code simple)
            return self._request("POST", path, params=params, json_body=body, expected=(200, 201)).json()[0]
        raise RuntimeError(f"Failed UPSERT message: {resp.status_code} {resp.text}")

    def log_inbound(self, evt: EventDTO) -> Dict[str, Any]:
        """
        Idempotent UPSERT into dev_nexus.event using (provider_ref, direction).
        """
        body = evt.model_dump(exclude_none=True)
        headers = {**self._common_headers, "Prefer": "return=representation,resolution=merge-duplicates"}
        path = "/rest/v1/event"
        params = {"on_conflict": "provider_ref,direction"}
        resp = self._session.post(
            f"{self.cfg.base_url}{path}",
            headers=headers,
            params=params,
            json=body,
            timeout=self.cfg.timeout_seconds,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return data[0] if isinstance(data, list) and data else data
        if resp.status_code in RETRYABLE:
            return self._request("POST", path, params=params, json_body=body, expected=(200, 201)).json()[0]
        raise RuntimeError(f"Failed UPSERT event: {resp.status_code} {resp.text}")

    def get_enrollment_status(self, enrollment_id: str) -> EnrollmentStatusDTO:
        """
        Deterministic status: if has outcome -> 'completed'; elif has handoff -> 'handoff'; else enrollment.status or 'unknown'.
        """
        # enrollment
        enr = self._request(
            "GET",
            "/rest/v1/enrollment",
            params={"id": f"eq.{enrollment_id}", "select": "id,status"},
        ).json()
        if not enr:
            return EnrollmentStatusDTO(
                enrollment_id=enrollment_id, status="unknown", has_outcome=False, has_handoff=False, computed="unknown"
            )
        status = enr[0].get("status") or "unknown"
        # outcome?
        oc = self._request(
            "GET",
            "/rest/v1/outcome",
            params={"enrollment_id": f"eq.{enrollment_id}", "select": "id", "limit": 1},
        ).json()
        # handoff?
        ho = self._request(
            "GET",
            "/rest/v1/handoff",
            params={"enrollment_id": f"eq.{enrollment_id}", "select": "id", "limit": 1},
        ).json()
        has_outcome = bool(oc)
        has_handoff = bool(ho)
        computed = "completed" if has_outcome else ("handoff" if has_handoff else (status if status else "unknown"))
        return EnrollmentStatusDTO(
            enrollment_id=enrollment_id,
            status=status,
            has_outcome=has_outcome,
            has_handoff=has_handoff,
            computed=computed,  # deterministic mapping
        )

    def link_ref_to_workflow(self, link: LinkRefDTO) -> Dict[str, Any]:
        """
        Record a linkage event (type='link') tying a provider_ref to a workflow/execution id.
        Idempotent on (provider_ref, direction='outbound') so multiple calls do not duplicate.
        """
        evt = EventDTO(
            provider_ref=link.provider_ref,
            direction="outbound",
            type="link",
            project_id=link.project_id,
            data={"workflow_id": link.workflow_id, "notes": link.notes} if link.notes else {"workflow_id": link.workflow_id},
        )
        return self.log_inbound(evt)
