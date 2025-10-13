# app/orchestrator/langgraph/graph.py
from langgraph.graph import StateGraph, END
from typing import TypedDict, Literal, List, Dict, Any
import asyncio
from app.data.db import fetch_due_actions


# ---------------------------
# State Definition
# ---------------------------

class OrchestratorState(TypedDict):
    """State structure passed between graph nodes."""
    jobs: List[Dict[str, Any]]


# ---------------------------
# Node Implementations
# ---------------------------

async def fetch_node(state: OrchestratorState) -> OrchestratorState:
    """Fetch pending actions (e.g., due campaign steps) from DB."""
    rows = await fetch_due_actions()
    return {"jobs": rows}


def route(job: Dict[str, Any]) -> str:
    """Determine next node based on channel type."""
    ch = job.get("next_channel")
    if ch == "sms":
        return "sms_node"
    if ch == "email":
        return "email_node"
    if ch == "voice":
        return "voice_node"
    return END


async def sms_node(state: OrchestratorState) -> OrchestratorState:
    """Placeholder for SMS dispatch or queuing logic."""
    # Here, you’d call Temporal activity or enqueue into channel worker.
    return state


async def email_node(state: OrchestratorState) -> OrchestratorState:
    """Placeholder for Email dispatch."""
    return state


async def voice_node(state: OrchestratorState) -> OrchestratorState:
    """Placeholder for Voice call dispatch."""
    return state


# ---------------------------
# Graph Builder
# ---------------------------

def build_orchestrator():
    """
    Build a simple orchestrator flow graph:
      fetch -> conditional route -> channel node -> END
    """
    g = StateGraph(OrchestratorState)

    # Register nodes
    g.add_node("fetch", fetch_node)
    g.add_node("sms_node", sms_node)
    g.add_node("email_node", email_node)
    g.add_node("voice_node", voice_node)

    g.set_entry_point("fetch")

    # Conditional edge: route based on next_channel
    g.add_conditional_edges(
        "fetch",
        lambda s: route(s["jobs"][0]) if s.get("jobs") else END,
        {
            "sms_node": "sms_node",
            "email_node": "email_node",
            "voice_node": "voice_node",
            END: END,
        },
    )

    # Terminal edges
    g.add_edge("sms_node", END)
    g.add_edge("email_node", END)
    g.add_edge("voice_node", END)

    return g.compile()


# ---------------------------
# Multi-Step Builder (C3.1)
# ---------------------------

def build_multistep_graph(base_payload: dict) -> List[Dict[str, Any]]:
    """
    Build a deterministic 3-step campaign flow (used by test_multistep.py)
    Each step includes channel, payload, wait time, and optional failure branch.
    """
    return [
        {
            "action": "send_email",
            "channel": "email",
            "payload": {**base_payload, "template": "intro"},
            "wait_hours": 1,
            "on_failure": 2,  # jump to fallback SMS
        },
        {
            "action": "send_sms",
            "channel": "sms",
            "payload": {**base_payload, "body": "Did you see our email?"},
            "wait_hours": 2,
        },
        {
            "action": "voice_start",
            "channel": "voice",
            "payload": {**base_payload, "agent_id": "followup_agent"},
        },
    ]
