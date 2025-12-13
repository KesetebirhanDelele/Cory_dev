# app/orchestrator/temporal/activities/rag.py
from __future__ import annotations

import os
import ssl
import urllib.parse
from typing import Any, Dict, List, Optional

from temporalio import activity

# --------------------------------------------------------------------------
# DB Connection (asyncpg)
# --------------------------------------------------------------------------
try:
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover
    asyncpg = None  # type: ignore


_POOL: "asyncpg.pool.Pool | None" = None  # type: ignore


async def _get_pool():
    """
    Lazily create a global asyncpg pool using DATABASE_URL / SUPABASE_DB_URL.

    We intentionally mimic `sslmode=require` semantics but relax verification,
    since Supabase often uses a self-signed cert in the chain.
    """
    global _POOL
    if _POOL is not None:
        return _POOL

    if asyncpg is None:
        raise RuntimeError("asyncpg not installed. Run: pip install asyncpg")

    dsn = (
        os.getenv("DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("POSTGRES_URL")
    )
    if not dsn:
        raise RuntimeError("DATABASE_URL / SUPABASE_DB_URL / POSTGRES_URL not set")

    u = urllib.parse.urlparse(dsn)
    q = dict(urllib.parse.parse_qsl(u.query or ""))

    host = (u.hostname or "").lower()
    use_ssl = False
    if host.endswith("supabase.co") or host.endswith("pooler.supabase.com"):
        use_ssl = True
    if q.get("sslmode") in {"require", "verify-ca", "verify-full"}:
        use_ssl = True

    sslctx = None
    if use_ssl:
        sslctx = ssl.create_default_context()
        sslctx.check_hostname = False
        sslctx.verify_mode = ssl.CERT_NONE

    activity.logger.info(
        "RAG _get_pool: creating asyncpg pool | host=%s ssl=%s",
        host or "unknown",
        bool(sslctx),
    )

    _POOL = await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=5,
        command_timeout=60,
        ssl=sslctx,
    )
    return _POOL


# --------------------------------------------------------------------------
# Embeddings for query → pgvector
# --------------------------------------------------------------------------
try:
    from openai import AsyncOpenAI  # openai>=1.0
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore

_EMBED_CLIENT: "AsyncOpenAI | None" = None  # type: ignore
EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


async def _get_embed_client():
    global _EMBED_CLIENT
    if _EMBED_CLIENT is None:
        if AsyncOpenAI is None:
            raise RuntimeError("openai not installed. Run: pip install openai")
        _EMBED_CLIENT = AsyncOpenAI()
    return _EMBED_CLIENT


async def _embed_query(text: str) -> Optional[str]:
    """
    Return query embedding as a pgvector-compatible string '[0.1,0.2,...]'.
    If embeddings are unavailable, return None so we can fall back to FTS.
    """
    if not text.strip():
        return None

    try:
        client = await _get_embed_client()
    except Exception as e:
        activity.logger.warning("RAG embed: no client (%s), skipping embeddings", e)
        return None

    try:
        resp = await client.embeddings.create(
            model=EMBED_MODEL,
            input=text,
        )
        vec = resp.data[0].embedding
        return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
    except Exception as e:
        activity.logger.warning("RAG embed: embedding failed (%s), falling back", e)
        return None


# --------------------------------------------------------------------------
# 1) RETRIEVE — expects ONE dict arg
# --------------------------------------------------------------------------
@activity.defn(name="retrieve_chunks")
async def retrieve_chunks(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieve relevant doc chunks for a given query.

    Expected input:
        { "query": str, "threshold": float }

    Returns:
        { "chunks": [ {id, doc_id, content, metadata, title, source, rank}, ... ] }
    """
    query: str = (args.get("query") or "").strip()
    threshold: float = float(args.get("threshold", 0.5))  # not used yet, but kept

    activity.logger.info(
        "RAG retrieve | query=%s | threshold=%.2f",
        query,
        threshold,
    )

    if not query:
        activity.logger.warning("RAG retrieve: empty query, returning no chunks")
        return {"chunks": []}

    # 1️⃣ Get DB pool
    try:
        pool = await _get_pool()
    except Exception as e:
        activity.logger.warning(
            "RAG retrieve: DB connection failed, returning no chunks: %s",
            e,
        )
        return {"chunks": []}

    # 2️⃣ Try vector similarity first (if embeddings + client available)
    query_vec = await _embed_query(query)

    async with pool.acquire() as conn:
        rows = []

        if query_vec is not None:
            try:
                vec_sql = """
                    SELECT
                        c.id,
                        c.doc_id,
                        c.content,
                        c.metadata,
                        d.title,
                        d.source,
                        1.0 - (c.embedding <=> $1::vector) AS rank
                    FROM doc_chunks c
                    JOIN docs d ON d.id = c.doc_id
                    WHERE c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> $1::vector
                    LIMIT 5;
                """
                rows = await conn.fetch(vec_sql, query_vec)
                activity.logger.info(
                    "RAG retrieve: vector search returned %d rows", len(rows)
                )
            except Exception as e:
                activity.logger.warning(
                    "RAG retrieve: vector search failed (%s), falling back to FTS",
                    e,
                )

        # 3️⃣ If vector search gave nothing or wasn't available → FTS fallback
        if not rows:
            ft_sql = """
                WITH q AS (
                    SELECT websearch_to_tsquery('english', $1) AS query
                )
                SELECT
                    c.id,
                    c.doc_id,
                    c.content,
                    c.metadata,
                    d.title,
                    d.source,
                    ts_rank_cd(
                        to_tsvector('english', coalesce(c.content, '')),
                        q.query
                    ) AS rank
                FROM doc_chunks c
                JOIN docs d ON d.id = c.doc_id,
                     q
                WHERE to_tsvector('english', coalesce(c.content, '')) @@ q.query
                ORDER BY rank DESC, c.id ASC
                LIMIT 5;
            """
            rows = await conn.fetch(ft_sql, query)

            if not rows:
                # Final fallback: just return latest docs so compose can at least say something
                activity.logger.info(
                    "RAG retrieve: no FTS matches for '%s' — falling back to latest chunks",
                    query,
                )
                fallback_sql = """
                    SELECT
                        c.id,
                        c.doc_id,
                        c.content,
                        c.metadata,
                        d.title,
                        d.source,
                        0.0::float AS rank
                    FROM doc_chunks c
                    JOIN docs d ON d.id = c.doc_id
                    ORDER BY c.id DESC
                    LIMIT 5;
                """
                rows = await conn.fetch(fallback_sql)

    chunks: List[Dict[str, Any]] = [dict(r) for r in rows]
    activity.logger.info("RAG retrieve: returning %d chunk(s)", len(chunks))
    return {"chunks": chunks}
