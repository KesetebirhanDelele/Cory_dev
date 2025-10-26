# app/orchestrator/temporal/workflows/program_match.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy           # <-- use object, not dict

from app.orchestrator.temporal.config import AI_MATCH_QUEUE

with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.program_match import (
        load_rules,
        deterministic_score,
        llm_score_fallback,
        persist_scores,
    )

@dataclass
class Score:
    program_id: str
    score: float
    source: str  # 'rules' | 'llm'

@dataclass
class MatchResult:
    lead_id: str
    rules_version: int
    fingerprint: str
    scores: List[Score]

# Common retry configs
RULES_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)
DET_RETRY = RULES_RETRY
LLM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
)
PERSIST_RETRY = RULES_RETRY

@workflow.defn(name="ProgramMatchWf")
class ProgramMatchWf:
    def __init__(self) -> None:
        self._lead_id: Optional[str] = None
        self._latest: Optional[MatchResult] = None

    @workflow.run
    async def run(self, lead_id: str) -> MatchResult:
        self._lead_id = lead_id

        rules = await workflow.execute_activity(
            load_rules,
            schedule_to_close_timeout=timedelta(seconds=20),
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=RULES_RETRY,
            task_queue=AI_MATCH_QUEUE,
        )

        det = await workflow.execute_activity(
            deterministic_score,
            {"lead_id": lead_id, "rules_version": rules["version"]},
            schedule_to_close_timeout=timedelta(seconds=20),
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=DET_RETRY,
            task_queue=AI_MATCH_QUEUE,
        )

        scores = det["scores"]
        gaps = det.get("gaps", [])

        if gaps:
            llm = await workflow.execute_activity(
                llm_score_fallback,
                {"lead_id": lead_id, "gaps": gaps, "rules_version": rules["version"]},
                schedule_to_close_timeout=timedelta(seconds=60),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=LLM_RETRY,
                task_queue=AI_MATCH_QUEUE,
            )
            scores.extend(llm["scores"])

        result: MatchResult = await workflow.execute_activity(
            persist_scores,
            {
                "lead_id": lead_id,
                "scores": scores,
                "rules_version": rules["version"],
                "fingerprint": det["fingerprint"],
            },
            schedule_to_close_timeout=timedelta(seconds=20),
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=PERSIST_RETRY,
            task_queue=AI_MATCH_QUEUE,
        )

        self._latest = result
        return result

    @workflow.signal
    async def LeadUpdated(self, lead_id: str):
        await workflow.continue_as_new(lead_id)

    @workflow.query
    def CurrentScores(self) -> Optional[MatchResult]:
        return self._latest
