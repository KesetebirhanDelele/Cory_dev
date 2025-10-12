# tests/docs/test_agent_catalog.py
import importlib

def test_catalog_schema_and_coverage():
    mod = importlib.import_module("app.agents.agent_catalog")
    catalog = mod.get_catalog()

    # Basic shape
    assert catalog.version.startswith("C0.1")
    assert len(catalog.agents) >= 3

    # Names present
    names = {a.name for a in catalog.agents}
    assert {"ContentGenerator", "ReplyInterpreter", "PolicyAwarePlanner"} <= names

    # Each agent has at least one input & output and lists tools
    for a in catalog.agents:
        assert len(a.inputs) > 0, f"{a.name} has no inputs"
        assert len(a.outputs) > 0, f"{a.name} has no outputs"
        assert len(a.tools) > 0, f"{a.name} has no tools"

    # Skills coverage: F1 & F2 must exist and map to defined agents
    coverage = catalog.skills_coverage
    assert "F1" in coverage and "F2" in coverage
    for skill, agents in coverage.items():
        assert len(agents) > 0, f"{skill} has no agents"
        for agent in agents:
            assert agent in names, f"{skill} references unknown agent {agent}"
