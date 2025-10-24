# app/orchestrator/temporal/activities/rag_retrieve.py
from __future__ import annotations
import os, asyncio, ssl, urllib.parse, logging, json
from typing import List, Dict, Any
from temporalio import activity

try:
    import asyncpg
except Exception:
    asyncpg = None  # type: ignore

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_PROJECT_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

log = logging.getLogger(__name__)

@activity.defn
async def retrieve_chunks(question: str):
    try:
        if os.getenv("DATABASE_URL"):
            log.info("retrieve_chunks using Postgres path")
            # ... your PG query ...
        else:
            log.info("retrieve_chunks using Supabase REST path")
            # ... your REST GET to /doc_chunks?select=...&limit=...
        # return chunks (list of {content, metadata, source, …})
    except Exception as e:
        log.exception("retrieve_chunks failed: %s", e)
        # Make the error visible in Temporal
        raise

def _http_headers():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase REST not configured")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

async def _http_get(path_with_query: str, timeout=10):
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    def _do():
        req = Request(f"{SUPABASE_URL}{path_with_query}", method="GET")
        for k,v in _http_headers().items():
            req.add_header(k,v)
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return await asyncio.to_thread(_do)

async def _pg_pool_or_none():
    dsn = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or os.getenv("POSTGRES_URL")
    if not dsn or asyncpg is None:
        return None
    u = urllib.parse.urlparse(dsn)
    sslctx = None
    if "supabase.co" in (u.hostname or ""):
        sslctx = ssl.create_default_context()
        sslctx.check_hostname = True
    try:
        return await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, timeout=6.0, command_timeout=10.0, ssl=sslctx)
    except Exception:
        return None

@activity.defn(name="retrieve_chunks")
async def retrieve_chunks(question: str) -> List[Dict[str, Any]]:
    # Try Postgres first (fast timeout)
    pool = await _pg_pool_or_none()
    if pool:
        async with pool.acquire() as conn:
            # simple ILIKE fallback if pgvector isn’t available in your env
            rows = await conn.fetch("""
                select doc_id, content, metadata
                from doc_chunks
                where content ilike '%' || $1 || '%'
                order by id desc
                limit 8
            """, question)
            return [dict(r) for r in rows]

    # Fallback to Supabase REST (fast timeout, simple text search)
    if SUPABASE_URL and SUPABASE_KEY:
        # Use PostgREST `ilike` filter; this is not vector sim but good for dev
        from urllib.parse import urlencode, quote
        q = urlencode({
            "select": "doc_id,content,metadata",
            "content": f"ilike.*{question}*",
            "limit": "8",
            "order": "id.desc",
        }, doseq=True)
        rows = await _http_get(f"/rest/v1/doc_chunks?{q}", timeout=8)
        return rows or []

    # Nothing configured → fail fast with a clear message
    raise activity.ApplicationError(
        "No data source for retrieve_chunks. Set DATABASE_URL (Postgres) or SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.",
        non_retryable=True,
    )
