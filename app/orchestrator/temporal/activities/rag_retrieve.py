# app/orchestrator/temporal/activities/rag_retrieve.py
from temporalio import activity
from app.data import db
from typing import Any, Dict, List

@activity.defn(name="retrieve_chunks")
async def retrieve_chunks(query: str, inbound_id: str, threshold: float) -> List[Dict[str, Any]]:
    activity.logger.info("Starting Supabase retrieval | query=%s | threshold=%.2f", query, threshold)

    try:
        chunks = db.retrieve_rag_chunks(query=query, threshold=threshold)
    except Exception as e:
        activity.logger.error("Supabase retrieval failed: %s", e)
        return []

    if not chunks:
        activity.logger.warning("No results found for query='%s'", query)
    else:
        activity.logger.info("Retrieved %d chunks", len(chunks))

    return chunks
