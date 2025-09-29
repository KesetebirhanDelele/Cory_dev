# orchestrator_graph.py
from langgraph.graph import StateGraph, END
from typing import TypedDict, Literal, List, Dict, Any
import asyncio
from app.data.db import fetch_due_actions

class OrchestratorState(TypedDict):
    jobs: List[Dict[str, Any]]

async def fetch_node(state: OrchestratorState):
    rows = await fetch_due_actions()
    return {"jobs": rows}

def route(job):
    ch = job["next_channel"]
    if ch == "sms": return "sms_node"
    if ch == "email": return "email_node"
    if ch == "voice": return "voice_node"
    return "done"

async def sms_node(state: OrchestratorState):
    # emit to queue or call agent directly (see sms_sender.py)
    return state

async def email_node(state: OrchestratorState): return state
async def voice_node(state: OrchestratorState): return state

def build_orchestrator():
    g = StateGraph(OrchestratorState)
    g.add_node("fetch", fetch_node)
    g.add_node("sms_node", sms_node)
    g.add_node("email_node", email_node)
    g.add_node("voice_node", voice_node)

    g.set_entry_point("fetch")
    # fan-out per job (simplified: one-by-one)
    g.add_conditional_edges("fetch", lambda s: route(s["jobs"][0]) if s["jobs"] else END,
                            {"sms_node":"sms_node","email_node":"email_node","voice_node":"voice_node", END: END})
    g.add_edge("sms_node", END); g.add_edge("email_node", END); g.add_edge("voice_node", END)
    return g.compile()
