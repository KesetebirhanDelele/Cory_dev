# B2.2 — Enrollment State Snapshot (dev_nexus)

Input: **latest** `dev_nexus.campaign_activity` row per `enrollment_id`, chosen by
`coalesce(completed_at, started_at, due_at, created_at) desc`.

Mapping (first match wins):

1. `result_payload.policy_denied = true` → **policy_denied**
2. `result_payload.timeout = true` or `result_summary = 'no_answer'` → **timeout**
3. `status = 'failed'` → **failed**
4. `status = 'completed'` → **delivered**
5. `status = 'in_progress'` → **sent**
6. `status = 'pending'` or anything else → **queued**

Notes:
- `campaign_activity` schema & statuses.
- Voice logger writes `result_summary` (e.g., `'no_answer'`).
