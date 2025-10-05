from supabase import create_client
import os
from dotenv import load_dotenv, find_dotenv
import pytest

load_dotenv(find_dotenv(filename=".env", usecwd=True) or find_dotenv(filename=".env.test", usecwd=True))

url = os.environ["SUPABASE_URL"]
key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not key:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY or SUPABASE_SERVICE_ROLE_KEY")

sb = create_client(url, key)
SCHEMA = os.getenv("DB_SCHEMA", "dev_nexus")

db = sb.postgrest.schema(SCHEMA)

def rows_to_set(rows, key):
    return {r[key] for r in rows}

@pytest.mark.order(1)
def test_tables_exist():
    rows = db.rpc("inspect_tables", {"p_schema": SCHEMA}).execute().data
    have = rows_to_set(rows, "table_name")

    expected = {
        "enrollment","message","event","outcome",
        "template","template_variant","handoff",
        "tenant","project","contact","campaign"
    }
    missing = expected - have
    assert not missing, f"Missing tables in schema {SCHEMA}: {sorted(missing)}"

@pytest.mark.order(2)
def test_foreign_keys_valid():
    rows = db.rpc("inspect_foreign_keys", {"p_schema": SCHEMA}).execute().data
    triples = {(r["child_table"], r["child_column"], r["parent_table"]) for r in rows}

    expected = {
        ("project","tenant_id","tenant"),
        ("contact","project_id","project"),
        ("campaign","project_id","project"),
        ("enrollment","project_id","project"),
        ("enrollment","campaign_id","campaign"),
        ("enrollment","contact_id","contact"),
        ("message","project_id","project"),
        ("event","project_id","project"),
        ("outcome","enrollment_id","enrollment"),
        ("handoff","enrollment_id","enrollment"),
    }
    missing = expected - triples
    assert not missing, f"Missing FKs: {sorted(missing)}"

@pytest.mark.order(3)
def test_unique_provider_ref_direction_on_message_and_event():
    rows = db.rpc("inspect_indexes", {
        "p_schema": SCHEMA,
        "p_tables": ["message", "event"]
    }).execute().data

    def has_unique_pair(table: str) -> bool:
        for r in rows:
            if r["table_name"] != table: 
                continue
            if not r["is_unique"]:
                continue
            d = r["index_def"] or ""
            # Accept plain pair or COALESCE/partial variants
            if "(provider_ref, direction)" in d:
                return True
            if "COALESCE(provider_ref" in d and "direction)" in d:
                return True
        return False

    assert has_unique_pair("message"), "Unique(provider_ref, direction) missing on message"
    assert has_unique_pair("event"),   "Unique(provider_ref, direction) missing on event"
