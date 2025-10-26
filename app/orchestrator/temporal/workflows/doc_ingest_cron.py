# app/orchestrator/temporal/workflows/doc_ingest_cron.py
from __future__ import annotations
from typing import Dict, Any
from temporalio import workflow

@workflow.defn
class DocIngestCronWf:
    @workflow.run
    async def run(self) -> Dict[str, Any]:
        # TODO: pull sources → chunk/emb → upsert vectors → version bump
        # Keep as a stub so scheduling doesn’t fail.
        return {"status": "noop"}
