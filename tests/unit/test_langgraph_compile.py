# tests/unit/test_langgraph_compile.py
from app.orchestrator.langgraph.graph import build_orchestrator

def test_graph_compiles():
    g = build_orchestrator()
    assert g is not None
