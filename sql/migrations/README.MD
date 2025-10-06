README
Overview

This repo contains the core database schema for Ticket B1.1 — Core Schema & Indexes and two test suites that verify:

required tables exist,

foreign keys are valid,

unique (provider_ref, direction) indexes are present.

You’ll run one migration script and two test scripts in this order.

Prereqs

Supabase project (not paused)

Service role key (for tests)

Python v3.10+ with pytest, python-dotenv, supabase (supabase-py v2)

.env at repo root:

SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service-role-key>
DB_SCHEMA=dev_nexus

One-time dashboard step (not scriptable):
Supabase Studio → Project Settings → API → Schemas exposed to the REST API → add dev_nexus.

Files you will run (and sequence)

Migration — creates schema, FKs, unique indexes, grants, and RPCs
db/migrations/001_core_schema.sql

Schema smoke test — verifies tables, FKs, and unique indexes via RPCs
tests/sql/test_schema_supabase_rpc.py

Acceptance test — same checks framed as the formal ticket test
tests/sql/test_schema.py

How to run
1) Apply migration

Option A: Supabase CLI

RUN THE CONTENT OF THIS FILES IN SUPABASE IN SQL EDITOR or use this
code but I have't tested it:

supabase db execute --file db/migrations/001_core_schema.sql 

Option B: psql (but I have not tested it)

psql "$DATABASE_URL" -f db/migrations/001_core_schema.sql 

If you re-run often, that SQL is idempotent.

2) Run the schema smoke test
pytest -q tests/sql/test_schema_supabase_rpc.py

3) Run the acceptance test
pytest -q tests/sql/test_schema.py

Expected outcome

Both tests pass:

tests/sql/test_schema_supabase_rpc.py → ✅

tests/sql/test_schema.py → ✅

Unique indexes on (provider_ref, direction) exist on dev_nexus.message and dev_nexus.event.

All required FKs are present (project↔tenant, contact/campaign/enrollment↔project, outcome/handoff↔enrollment, message/event↔project).

Troubleshooting (quick)

401 Invalid API key → Check .env keys, ensure service role key, no trailing spaces.

404 on /rest → Ensure dev_nexus is exposed in Studio → API settings.

42501 permission denied → Re-apply migration (it grants usage/select + defaults).

Function not found (PGRST202) → Migration creates public.inspect_* and dev_nexus wrappers; re-apply migration.