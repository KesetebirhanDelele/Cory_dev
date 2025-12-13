# debug_env.py
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore


# ---------------------------------------------------------------------
# Load .env from project root
# ---------------------------------------------------------------------
def load_project_env() -> None:
    project_root = Path(__file__).resolve().parent
    env_path = project_root / ".env"

    print(f"Using .env at: {env_path}")

    if not env_path.exists():
        print("⚠️ .env file does NOT exist at that path")
    else:
        load_dotenv(env_path, override=True)
        print("[debug_env] .env loaded")


# ---------------------------------------------------------------------
# Test one DSN by connecting and selecting from docs
# ---------------------------------------------------------------------
async def test_dsn(name: str, dsn: str) -> None:
    if psycopg is None:
        print("❌ psycopg is not installed. Run: pip install psycopg[binary]")
        return

    print(f"\n--- Testing {name} ---")
    print(f"{name} = {dsn!r}")

    def _run_query() -> List[Dict[str, Any]]:
        # Synchronous code that will be run in a thread
        with psycopg.connect(dsn, connect_timeout=20) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM docs LIMIT 5;")
                return list(cur.fetchall())

    loop = asyncio.get_running_loop()

    try:
        print(f"[{name}] Connecting via psycopg...")
        rows = await loop.run_in_executor(None, _run_query)
        print(f"[{name}] ✅ Connected")
        print(f"[{name}] Rows from docs (up to 5):")

        if not rows:
            print(f"[{name}]   (no rows)")
        else:
            for r in rows:
                doc_id = r.get("id")
                title = r.get("title")
                print(f"  - id={doc_id!r}, title={title!r}, full_row={r}")

        print(f"[{name}] ✅ Query succeeded")

    except Exception as e:
        print(f"[{name}] ❌ Connection or query failed: {repr(e)}")


# ---------------------------------------------------------------------
# Main async driver
# ---------------------------------------------------------------------
async def main_async() -> None:
    load_project_env()

    print("\n=== Current env values ===")
    db_url = os.getenv("DATABASE_URL")
    supabase_db_url = os.getenv("SUPABASE_DB_URL")
    postgres_url = os.getenv("POSTGRES_URL")

    print("DATABASE_URL      :", db_url)
    print("SUPABASE_DB_URL   :", supabase_db_url)
    print("POSTGRES_URL      :", postgres_url)

    candidates: list[tuple[str, Optional[str]]] = [
        ("DATABASE_URL", db_url),
        ("SUPABASE_DB_URL", supabase_db_url),
        ("POSTGRES_URL", postgres_url),
    ]

    for name, dsn in candidates:
        if dsn:
            await test_dsn(name, dsn)
        else:
            print(f"\n--- Skipping {name} (not set) ---")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
