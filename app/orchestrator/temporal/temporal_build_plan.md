# Temporal-first Build Plan (orchestrator/temporal)

| Phase | File(s) to build | Purpose (what you implement) | Depends on | How to test | Example command |
|------:|-------------------|------------------------------|------------|-------------|-----------------|
| 1 | `app/orchestrator/temporal/worker.py` | Start a Temporal **Worker** and register workflows/activities (can start empty). | Temporal server reachable; `temporalio` installed. | **Smoke:** run worker; it idles without crashing. | `python -m app.orchestrator.temporal.worker` |
| 2 | `activities/sms_send.py`, `email_send.py`, `voice_start.py` | **Stub activities**: accept `(enrollment_id, payload)` and return dummy refs; no network yet. | — | **Unit:** import and call each function; assert return shape. | `pytest -q tests/unit/test_temporal_activities.py::test_sms_stub` |
| 3 | `workflows/campaign.py` | Minimal **workflow**: execute one activity, **wait for `provider_event` signal**, then complete or single backoff. | 1–2 | **Integration:** start workflow, send signal, assert it closes. | `pytest -q tests/integration/test_campaign_workflow.py::test_signal_completes` |
| 4 | `app/web/webhook.py` (outside) | Add **webhook route** that gets Temporal handle and **signals** `provider_event` (HMAC later). | 3 | **Integration:** POST webhook → workflow receives signal → completes. | `pytest -q tests/integration/test_webhook_signal.py` |
| 5 | `activities/interactions_log.py` | Write interaction/staging rows to DB via repo (normalized status/timestamps). | DB repo & tables | **Unit:** mock repo; **Integration:** insert then assert row exists. | `pytest -q tests/unit/test_interactions_log.py` |
| 6 | (Replace stubs) `sms_send.py`, `email_send.py`, `voice_start.py` | Call **real providers** (`app/channels/providers/*`); pass idempotency key; map response `{provider_ref,status}`. | Provider clients; secrets in settings | **Unit (mock HTTP):** assert headers/retry; **Integration:** sandbox/mock server. | `pytest -q tests/unit/test_sms_send_live_mock.py` |
| 7 | `common/retry_policies.py` and wire into workflow/activities | Centralize **timeouts/retry policies**; pass kwargs to `execute_activity`. | — | **Integration:** force retryable error and observe retries. | `pytest -q tests/integration/test_activity_retries.py` |
| 8 | expand `workflows/campaign.py` | Full loop: **send → wait (signal/timeout) → progress/backoff → optional escalate** (`handoff_create`). | 5–7 | **Integration:** two failed signals then escalate called. | `pytest -q tests/integration/test_campaign_backoff_escalate.py` |
| 9 | `activities/handoff_create.py` | Create **Slack/Ticket**; return `ticket_id` (no-op in dev ok). | Slack client (or stub) | **Unit:** mock client; assert request shape. | `pytest -q tests/unit/test_handoff_create.py` |
| 10 *(optional)* | `workflows/schedules.py` | Temporal **Schedules/cron** if you won’t use your old scheduler. | Temporal Schedule API | **Integration:** create schedule; next action fires. | `python -m app.orchestrator.temporal.schedules` |
| 11 | hardening across files | **Idempotency, error mapping, structured logs, metrics**. | settings + repo | **E2E:** duplicate webhooks → only one state change & one DB row. | `pytest -q tests/e2e/test_duplicate_webhooks.py` |

## Test suite layout (suggested)
