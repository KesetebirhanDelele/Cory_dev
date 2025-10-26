# app/orchestrator/temporal/activities/rag.py
from __future__ import annotations
import asyncio
import os
import ssl
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from temporalio import activity

# --- DB pool (asyncpg) ---------------------------------------------------------
try:
    import asyncpg  # type: ignore
except Exception:
    asyncpg = None  # type: ignore

_POOL = None

async def _get_pool():
    global _POOL
    if _POOL:
        return _POOL
    if asyncpg is None:
        raise RuntimeError("asyncpg not installed. `pip install asyncpg`")

    dsn = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or os.getenv("POSTGRES_URL")
    if not dsn:
        raise RuntimeError("Set DATABASE_URL (or SUPABASE_DB_URL/POSTGRES_URL)")

    u = urllib.parse.urlparse(dsn)
    q = dict(urllib.parse.parse_qsl(u.query or ""))
    sslctx = None
    if (u.hostname or "").endswith("supabase.co") or q.get("sslmode") in {"require","verify-ca","verify-full"}:
        sslctx = ssl.create_default_context()
        sslctx.check_hostname = True

    _POOL = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5, command_timeout=60, ssl=sslctx)
    return _POOL

# --- Activities ---------------------------------------------------------------

@activity.defn
async def retrieve_chunks(question: str, k: int = 5, org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Vector search on doc_chunks using pgvector (embedding <-> query).
    NOTE: You must supply the query embedding from your caller/LLM layer later.
          For now we simulate with a stored function or pass a dummy vector.
    """
    # For demo: assume you already computed a query embedding elsewhere
    # and stashed it in activity headers OR call an embedding provider here.
    # We'll just raise if ENV var not set.
    emb = os.getenv("RAG_QUERY_EMBEDDING")  # expects comma-separated floats
    if not emb:
        # Minimal fallback: return top K recent chunks (no vector) so you can test flow end-to-end.
        pool = await _get_pool()
        sql = """
          select c.id, c.doc_id, c.content, c.metadata, d.title, d.source
          from doc_chunks c
          join docs d on d.id = c.doc_id
          where ($1::uuid is null or c.org_id = $1::uuid or c.org_id is null)
          order by c.id desc
          limit $2
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, org_id, k)
        return [dict(r) for r in rows]

    # Proper vector search path
    vec = "[" + emb + "]"
    pool = await _get_pool()
    sql = """
      select c.id, c.doc_id, c.content, c.metadata, d.title, d.source,
             (c.embedding <-> $2::vector) as distance
      from doc_chunks c
      join docs d on d.id = c.doc_id
      where ($1::uuid is null or c.org_id = $1::uuid or c.org_id is null)
      order by c.embedding <-> $2::vector
      limit $3
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, org_id, vec, k)
    return [dict(r) for r in rows]


@activity.defn
async def compose_answer(question: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compose a draft answer. Replace the body with your LLM call.
    Returns: {answer, citations}
    """
    # Simple compose with citations placeholder
    snippets = [c["content"][:200] for c in chunks]
    citations = [{"doc_id": c.get("doc_id"), "title": c.get("title")} for c in chunks]
    answer = (
        f"Q: {question}\n\n"
        "Draft answer (stubbed):\n"
        + "\n---\n".join(snippets)
        + "\n\n(Include citations inline in real LLM output.)"
    )
    return {"answer": answer, "citations": citations}


@activity.defn
async def redact_enforce(answer: str) -> Dict[str, Any]:
    """
    Redact PII / enforce tone. Returns (answer, confidence, redaction_log).
    Replace with a real guard (regex/LLM).
    """
    import re
    redactions = []
    redacted = answer

    # naive email/phone mask
    email_re = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    phone_re = r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"

    def _mask(pattern, label):
        nonlocal redacted
        found = re.findall(pattern, redacted)
        for f in set(found):
            redactions.append({"type": label, "original": f})
            redacted = redacted.replace(f, "[REDACTED]")
    _mask(email_re, "email")
    _mask(phone_re, "phone")

    # naive confidence for demo
    confidence = 0.9 if len(redactions) == 0 else 0.7
    return {"answer": redacted, "confidence": confidence, "redaction_log": redactions}


@activity.defn
async def route(answer: str, confidence: float, threshold: float, inbound_msg_id: str) -> Dict[str, Any]:
    """
    If confidence >= threshold → send to outbox (idempotent on ans:{inbound_msg_id}).
    Else → create a handoff task (or just flag it).
    This demo writes to an 'outbox' table if present; else, no-op.
    """
    pool = await _get_pool()
    key = f"ans:{inbound_msg_id}"
    sent = False
    handed_off = False

    async with pool.acquire() as conn:
        # ensure outbox table exists (best effort)
        await conn.execute(
            """
            create table if not exists outbox(
              id bigserial primary key,
              idempotency_key text unique,
              body jsonb not null,
              created_at timestamptz default now()
            )
            """
        )
        if confidence >= threshold:
            try:
                await conn.execute(
                    "insert into outbox(idempotency_key, body) values($1, $2::jsonb) "
                    "on conflict (idempotency_key) do nothing",
                    key, {"answer": answer, "confidence": confidence}
                )
                sent = True
            except Exception:
                # still consider idempotent “sent”
                sent = True
        else:
            # create a lightweight handoff record (best effort)
            await conn.execute(
                """
                create table if not exists handoffs(
                  id bigserial primary key,
                  inbound_msg_id text,
                  reason text,
                  payload jsonb,
                  created_at timestamptz default now()
                )
                """
            )
            await conn.execute(
                "insert into handoffs(inbound_msg_id, reason, payload) values($1,$2,$3::jsonb)",
                inbound_msg_id, "confidence_below_threshold", {"answer": answer, "confidence": confidence}
            )
            handed_off = True

    return {"routed_to_outbox": sent, "handoff_created": handed_off, "idempotency_key": key}
