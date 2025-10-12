# C1.3 — Error Taxonomy (Cory)

**Goal:** Standard codes so Dev-A can map provider errors consistently, and our workflow retries only when it should.

## Families

| Code | Retry? | Meaning / Examples |
|---|---|---|
| `timeout` | ✅ transient | Network or provider timeout; no response in window. |
| `throttled` | ✅ transient | 429/“rate limited”; retry with backoff. |
| `network_glitch` | ✅ transient | DNS/TLS/socket hiccup. |
| `policy_denied` | ❌ no | Quiet hours, no consent, DNC, org caps. |
| `invalid_payload` | ❌ no | Bad template/params; schema mismatch. |
| `quota_exhausted` | ❌ no | Hard provider quota exhausted (not a soft 429). |
| `permanent_failure` | ❌ no | Provider says permanent failure; do not retry. |
| `bounced` | ❌ no | Email hard bounce; never retry. |

## Mapping guidance
- If the provider returns 429 → `throttled`.
- If HTTP 5xx or connect/reset → `network_glitch` (unless timeout threshold crossed → `timeout`).
- Provider explicit “do not try again” → `permanent_failure`.
- Email hard bounce → `bounced`.
- Local policy guards → `policy_denied`.
