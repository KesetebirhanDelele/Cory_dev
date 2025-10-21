# C1.2 — Provider Event Signal Contract

This document defines the **`provider_event`** payload Cory’s workflow expects when a channel/provider finishes an attempt.

## Minimal Dict (wire shape)

```json
{
  "status": "delivered | failed | replied | completed | bounced | queued",
  "provider_ref": "string",       // provider’s message/call id
  "channel": "sms | email | voice",
  "activity_id": "string",        // our activity id (or external reference)
  "data": { "any": "json" }       // optional: raw/provider details, metrics
}
