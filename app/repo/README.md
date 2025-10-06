Ticket B1.3 — Python Repo APIs

This folder adds a tiny, typed Python “repo” layer that talks to Supabase/PostgREST and passes the B1.3 acceptance tests:

Idempotent log_outbound / log_inbound (no duplicates)

Deterministic get_enrollment_status

link_ref_to_workflow helper

Retries/backoff on transient DB/API errors

What was done

Code

app/repo/dtos.py — Pydantic DTOs for strong typing:

MessageDTO, EventDTO, LinkRefDTO, EnrollmentStatusDTO

app/repo/supabase_repo.py — HTTP repo using PostgREST:

log_outbound() → UPSERT into dev_nexus.message

log_inbound() → UPSERT into dev_nexus.event

get_enrollment_status() → computes completed/handoff/active/unknown

link_ref_to_workflow() → records an event (type='link')

Exponential backoff + retries for 408/429/5xx

Schema targeting via Accept-Profile: dev_nexus

Tests

tests/unit/test_supabase_repo.py — Mocks HTTP to verify:

Idempotent UPSERTs (uses on_conflict=provider_ref,direction + Prefer: resolution=merge-duplicates)

Deterministic status mapping

Retries/backoff behavior

link-to-workflow routes through /rest/v1/event

Assumptions/Dependencies

B1.1 schema exists and includes unique indexes on (provider_ref, direction) for message and event.

(Optional but recommended) B1.2 RLS in place; tests here don’t require live DB because they mock HTTP.

Repo layout (relevant files)
app/
  repo/
    dtos.py
    supabase_repo.py
tests/
  unit/
    test_supabase_repo.py
db/migrations/
  001_core_schema.sql     # from B1.1, schema and unique indexes
  002_rls_roles.sql       # from B1.2 (optional for these unit tests)

Setup

Python env

python -m venv .venv
./.venv/Scripts/activate    # Windows
# source .venv/bin/activate # macOS/Linux

pip install pydantic requests pytest python-dotenv


(Optional) Environment for running the repo against a real Supabase (not needed for unit tests)
Create .env at the repo root:

SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service-role-key>    # or SUPABASE_SERVICE_ROLE_KEY
DB_SCHEMA=dev_nexus


For B1.3 unit tests, the HTTP layer is mocked—no live keys required.

How to run tests
Unit tests for this ticket
pytest -q tests/unit/test_supabase_repo.py


What to expect

All tests pass.

Verifies idempotency (created → merged), deterministic status, retry/backoff, and correct routing for link refs.

Design notes (why this passes acceptance)

Idempotency: We rely on B1.1’s unique constraint via PostgREST UPSERT:

POST /rest/v1/<table>?on_conflict=provider_ref,direction

Header: Prefer: return=representation,resolution=merge-duplicates

Typed DTOs: pydantic models define strict payload shapes and defaults.

Retries/backoff: Exponential backoff for 408/429/5xx ensures robustness under load or transient DB glitches.

Deterministic status: get_enrollment_status computes:

outcome present → completed

else handoff present → handoff

else enrollment.status (or unknown)