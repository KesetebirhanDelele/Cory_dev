# app/web/voice_rag_answer.py

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, HTTPException
from openai import OpenAI

# Reuse the same custom-variable extraction logic as voice_webhook
from app.web.voice_webhook import _extract_custom_variables

router = APIRouter()
log = logging.getLogger("cory.voice.rag")

# ---------------------------
# OpenAI / embeddings
# ---------------------------
EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
_openai_client: Optional[OpenAI] = None


def get_openai_client() -> OpenAI:
    """
    Lazily instantiate the OpenAI client. Uses OPENAI_API_KEY from env.
    """
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


async def embed(text: str) -> List[float]:
    """
    Get an embedding for the question.

    Note: openai-python v1 client is sync under the hood; for now we call it
    directly. This is fine at the small QPS of voice tools.
    """
    client = get_openai_client()
    resp = client.embeddings.create(
        model=EMBED_MODEL,
        input=text,
    )
    return resp.data[0].embedding


def embedding_to_pgvector(values: List[float]) -> str:
    """
    Convert embedding list to pgvector's text format: `[0.1,0.2,...]`.
    """
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


# ---------------------------
# DB / pgvector
# ---------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
_db_pool: Optional[asyncpg.Pool] = None


async def get_db_pool() -> asyncpg.Pool:
    """
    Shared asyncpg connection pool for RAG queries.
    """
    global _db_pool
    if _db_pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        log.info(
            "[VoiceRAG] Creating asyncpg pool for voice RAG (DATABASE_URL=%s)",
            DATABASE_URL,
        )
        _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return _db_pool


async def fetch_chunks(
    question: str,
    org_id: Optional[str],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Simple vector search over doc_chunks filtered by org_id (if provided).
    Returns rows as dicts with content + metadata.
    """
    pool = await get_db_pool()
    emb = await embed(question)
    vec = embedding_to_pgvector(emb)

    where = "TRUE"
    params: List[Any] = [vec, limit]
    if org_id:
        where = "dc.org_id = $3"
        params.append(org_id)

    sql = f"""
        SELECT
            dc.doc_id,
            dc.content,
            dc.metadata,
            d.title,
            d.source
        FROM doc_chunks dc
        JOIN docs d ON d.id = dc.doc_id
        WHERE {where}
        ORDER BY dc.embedding <-> $1::vector
        LIMIT $2;
    """

    rows: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        recs = await conn.fetch(sql, *params)
        for r in recs:
            rows.append(
                {
                    "doc_id": str(r["doc_id"]),
                    "content": r["content"],
                    "metadata": r["metadata"],
                    "title": r.get("title"),
                    "source": r.get("source"),
                }
            )

    log.info("[VoiceRAG] Retrieved %d chunks for org_id=%s", len(rows), org_id)
    return rows


# ---------------------------
# Local compose logic (copy of rag_compose core)
# ---------------------------

def _normalize_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _any_in(text: str, needles: List[str]) -> bool:
    text = text.lower()
    return any(n in text for n in needles)


def _score_chunk(chunk: Dict[str, Any], question: str) -> float:
    q = (question or "").lower()
    content = str(chunk.get("content", "") or "").lower()
    meta = _normalize_metadata(chunk.get("metadata"))
    topic = str(meta.get("topic", "") or "").lower()
    section = str(meta.get("section", "") or "").lower()

    score = 0.0

    # Heuristic keyword boosts (same style as rag_compose)
    if _any_in(q, ["register", "registration", "enroll", "enrollment", "apply", "application"]):
        if _any_in(content, ["register", "registration", "enroll", "enrollment", "apply", "application"]):
            score += 5.0
        if _any_in(topic + " " + section, ["registration", "how_to_register"]):
            score += 3.0

    if _any_in(q, ["cost", "price", "tuition", "pay", "payment", "fee", "fees"]):
        if _any_in(content, ["tuition", "cost", "price", "payment", "installment", "pay", "fees"]):
            score += 5.0
        if _any_in(topic + " " + section, ["tuition", "financial", "financial_aid"]):
            score += 3.0

    if _any_in(q, ["class", "classes", "course", "courses", "program", "programs", "bootcamp", "training"]):
        if _any_in(
            content,
            [
                "program",
                "programs",
                "bootcamp",
                "course",
                "courses",
                "training",
                "data analytics",
                "data science",
            ],
        ):
            score += 3.0
        if _any_in(topic + " " + section, ["programs", "programs_overview"]):
            score += 2.0

    if _any_in(
        q,
        [
            "data analytics",
            "data science",
            "analytics",
            "power bi",
            "powerbi",
            "sql",
            "python",
            "tableau",
            "bi",
        ],
    ):
        if _any_in(
            content,
            [
                "data analytics",
                "data science",
                "power bi",
                "sql",
                "python",
                "tableau",
                "data visualization",
            ],
        ):
            score += 3.0

    # General lexical overlap
    q_tokens = set(re.findall(r"\w+", q))
    c_tokens = set(re.findall(r"\w+", content))
    if q_tokens and c_tokens:
        overlap = len(q_tokens & c_tokens)
        score += min(overlap, 20) * 0.2

    meta_text = f"{topic} {section}"
    m_tokens = set(re.findall(r"\w+", meta_text))
    if q_tokens and m_tokens:
        m_overlap = len(q_tokens & m_tokens)
        score += min(m_overlap, 10) * 0.3

    return score


def compose_from_chunks(question: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not chunks:
        return {
            "answer": (
                "I don’t have enough information in my knowledge base to answer that yet. "
                "A team member will follow up with more details."
            ),
            "citations": [],
        }

    ranked = sorted(chunks, key=lambda c: _score_chunk(c, question), reverse=True)
    top = ranked[:3]

    snippets = [
        str(c.get("content", "")).strip()
        for c in top
        if c.get("content")
    ]

    if not snippets:
        return {
            "answer": (
                "I’m not able to extract a clear answer from the available documents. "
                "A team member will follow up with more details."
            ),
            "citations": [],
        }

    # For voice, long answers can be painful; keep it moderate
    answer = "\n\n".join(snippets)
    if len(answer) > 1200:
        answer = answer[:1200] + "..."

    citations = [
        {
            "doc_id": c.get("doc_id"),
            "title": c.get("title"),
            "source": c.get("source"),
            "preview": str(c.get("content", "")).strip()[:120],
            "metadata": _normalize_metadata(c.get("metadata")),
        }
        for c in top
    ]

    return {"answer": answer, "citations": citations}


# ---------------------------
# Question extraction helpers
# ---------------------------

def _extract_question(payload: Dict[str, Any]) -> str:
    """
    Best-effort extraction of the *current* user question from a Synthflow-style payload.

    We support multiple shapes so you don't have to perfectly configure variables in Synthflow:
      1) payload["question"]
      2) payload["call"]["latest_user_message"] / ["user_utterance"] / ["user_message"]
      3) Last 'human:' or 'user:' line from call.transcript / payload.transcript
      4) payload["text"] or payload["body"] (last resort)
    """
    # 1) Direct question field
    q = (payload.get("question") or "").strip()
    if q:
        return q

    call = payload.get("call") or {}
    # 2) Dedicated fields from Synthflow call object
    for key in ("latest_user_message", "user_utterance", "user_message"):
        val = (call.get(key) or "").strip()
        if val:
            return val

    # 3) Try to pull last 'human:' / 'user:' line from transcript
    transcript = (
        call.get("transcript")
        or payload.get("transcript")
        or ""
    )
    if transcript:
        lines = [ln.strip() for ln in transcript.splitlines() if ln.strip()]
        human_lines = [
            ln for ln in lines
            if ln.lower().startswith("human:") or ln.lower().startswith("user:")
        ]
        if human_lines:
            last_line = human_lines[-1]
            # Strip leading "human:" / "user:"
            last_line = re.sub(r"^(human:|user:)\s*", "", last_line, flags=re.I)
            if last_line:
                return last_line.strip()

    # 4) Fallbacks
    for key in ("text", "body", "message"):
        val = (payload.get(key) or "").strip()
        if val:
            return val

    return ""


# ---------------------------
# HTTP endpoint for Synthflow
# ---------------------------

@router.post("/api/voice/rag-answer")
async def voice_rag_answer(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Live-call RAG endpoint for Synthflow / Colaberry.

    This is designed to work even if Synthflow just posts the *same kind*
    of JSON you already send to /api/voice/transcript, e.g.:

        {
          "call": { "call_id": "...", "transcript": "...", ... },
          "lead": {
            "name": "Evelyn Brooks",
            "phone_number": "+15714782790",
            "prompt_variables": {
              "org_id": "3333-...",
              "campaign_id": "7777-...",
              "enrollment_id": "bbbb-..."
            }
          },
          "status": "in_progress"  // or similar
          ...
        }

    We will:
      - Extract org_id / enrollment_id / campaign_id using the same logic
        as voice_webhook._extract_custom_variables().
      - Infer the *current* user question using _extract_question().
      - Query doc_chunks via pgvector.
      - Return a grounded answer for the voice bot to speak.

    Returns JSON:
        {
          "answer": "...",     # text for TTS
          "citations": [...]   # optional, for debugging / UI
        }
    """

    # Custom vars already know about org_id, enrollment_id, campaign_id, etc.
    custom_vars = _extract_custom_variables(payload)
    org_id = custom_vars.get("org_id")
    enrollment_id = custom_vars.get("enrollment_id")
    campaign_id = custom_vars.get("campaign_id")
    phone = (
        custom_vars.get("phone")
        or (payload.get("lead") or {}).get("phone_number")
        or (payload.get("lead") or {}).get("phone")
    )
    lead_name = (payload.get("lead") or {}).get("name")

    question = _extract_question(payload)
    if not question:
        log.warning(
            "[VoiceRAG] Missing question in payload; cannot run RAG. Keys=%s",
            list(payload.keys()),
        )
        raise HTTPException(
            status_code=400,
            detail="Missing 'question' / user utterance",
        )

    log.info(
        "[VoiceRAG] question=%s | org_id=%s | enrollment_id=%s | campaign_id=%s | phone=%s | lead_name=%s",
        question,
        org_id,
        enrollment_id,
        campaign_id,
        phone,
        lead_name,
    )

    chunks = await fetch_chunks(question=question, org_id=org_id, limit=5)
    result = compose_from_chunks(question, chunks)

    # -------------------------
    # Post-process for voice
    # -------------------------
    answer_text = result["answer"]

    # Flatten markdown bullets/headings into a single spoken-friendly string
    lines = [ln.strip() for ln in answer_text.splitlines() if ln.strip()]
    cleaned_lines = [
        re.sub(r"^\s*[-*#]+\s*", "", ln)  # remove leading -, *, # bullets/headings
        for ln in lines
    ]
    answer_text = " ".join(cleaned_lines)

    # Trim for voice (avoid super long monologues)
    if len(answer_text) > 600:
        answer_text = answer_text[:600].rsplit(" ", 1)[0] + "…"

    # Personalize with lead name if available
    if lead_name:
        answer_text = f"{lead_name}, {answer_text}"

    log.info(
        "[VoiceRAG] Returning answer (len=%d) for org_id=%s enrollment_id=%s",
        len(answer_text),
        org_id,
        enrollment_id,
    )

    # Keep response very simple for the voice agent
    return {
        "answer": answer_text,
        "citations": result["citations"],
    }
