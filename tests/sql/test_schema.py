# tests/sql/test_schema.py
import os
from typing import Iterable, Any, Dict, Set, Tuple

import pytest
from dotenv import load_dotenv, find_dotenv

try:
    from supabase import create_client  # supabase-py v2
except ImportError as e:
    raise RuntimeError(
        "supabase package not installed. Add `supabase` to your deps."
    ) from e


# ---- env & client ------------------------------------------------------------

# Load .env from repo root even when pytest runs from subdirs
load_dotenv(find_dotenv(filename=".env", usecwd=True) or find_dotenv(filename=".env.test", usecwd=True))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SCHEMA = os.environ.get("DB_SCHEMA", "dev_nexus")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL and/or SUPABASE_SERVICE_KEY in environment.")

db = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---- helpers -----------------------------------------------------------------

def rows_to_set(rows: Iterable[Dict[str, Any]], key: str) -> Set[Any]:
    return {r[key] for r in rows if key in r and r[key] is not None}


def _has_unique_pair(rows: Iterable[Dict[str, Any]], table: str) -> bool:
    """
    True if any unique index for `table` contains (provider_ref, direction).
    Accepts plain pair or COALESCE(...) variants produced by some DDLs.
    """
    for r in rows:
        if r.get("table_name") != table:
            continue
        if not r.get("is_unique"):
            continue
        d = (r.get("index_def") or "")
        # Accept typical variants
        if "(provider_ref, direction)" in d:
            return True
        if "COALESCE(provider_ref" in d and "direction)" in d:
            return True
    return False


# ---- tests -------------------------------------------------------------------

def test_tables_exist():
    """
    Migrations apply: required tables exist in target schema.
    """
    rows = db.rpc("inspect_tables", {"p_schema": SCHEMA}).execute().data
    have = rows_to_set(rows, "table_name")

    expected = {
        "tenant",
        "project",
        "contact",
        "campaign",
        "enrollment",
        "outcome",
        "handoff",
        "providers",
        "message",
        "event",
        "template",
        "template_variant",
    }

    missing = expected - have
    assert not missing, f"Missing tables in schema {SCHEMA}: {sorted(missing)}"


def test_foreign_keys_valid():
    """
    Foreign keys are present and point to the correct parent tables.
    """
    rows = db.rpc("inspect_foreign_keys", {"p_schema": SCHEMA}).execute().data

    triples: Set[Tuple[str, str, str]] = {
        (r["child_table"], r["child_column"], r["parent_table"]) for r in rows
    }

    expected = {
        ("project", "tenant_id", "tenant"),
        ("contact", "project_id", "project"),
        ("campaign", "project_id", "project"),
        ("enrollment", "project_id", "project"),
        ("enrollment", "campaign_id", "campaign"),
        ("enrollment", "contact_id", "contact"),
        ("message", "project_id", "project"),
        ("event", "project_id", "project"),
        ("outcome", "enrollment_id", "enrollment"),
        ("handoff", "enrollment_id", "enrollment"),
    }

    missing = expected - triples
    assert not missing, f"Missing FKs: {sorted(missing)}"


def test_unique_on_provider_ref_direction():
    """
    Unique index exists on (provider_ref, direction) for message and event.
    """
    rows = db.rpc(
        "inspect_indexes",
        {"p_schema": SCHEMA, "p_tables": ["message", "event"]},
    ).execute().data

    assert _has_unique_pair(rows, "message"), "Unique(provider_ref, direction) missing on message"
    assert _has_unique_pair(rows, "event"), "Unique(provider_ref, direction) missing on event"
