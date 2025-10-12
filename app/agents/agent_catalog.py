# app/agents/agent_catalog.py
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field

AgentName = Literal["ContentGenerator", "ReplyInterpreter", "PolicyAwarePlanner"]

class IOField(BaseModel):
    name: str
    type: str
    required: bool = True
    description: Optional[str] = None

class AgentSpec(BaseModel):
    name: AgentName
    purpose: str
    inputs: List[IOField]
    outputs: List[IOField]
    tools: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

class CatalogSpec(BaseModel):
    version: str = "C0.1"
    agents: List[AgentSpec]
    skills_coverage: Dict[str, List[AgentName]]  # keys: "F1", "F2"

def get_catalog() -> CatalogSpec:
    return CatalogSpec(
        agents=[
            AgentSpec(
                name="ContentGenerator",
                purpose="Produce first-draft outreach and subject lines.",
                inputs=[
                    IOField(name="brief", type="string"),
                    IOField(name="persona", type="string"),
                    IOField(name="goals", type="string"),
                    IOField(name="history", type="json", required=False),
                ],
                outputs=[
                    IOField(name="draft_text", type="string"),
                    IOField(name="tone", type="string"),
                    IOField(name="channel_hint", type="string", required=False),
                ],
                tools=["llm.openai", "templates.library", "telemetry.emit"],
                notes="Use deterministic templates if policy requires."
            ),
            AgentSpec(
                name="ReplyInterpreter",
                purpose="Classify inbound replies/calls; extract intents/entities.",
                inputs=[
                    IOField(name="text", type="string"),
                    IOField(name="channel", type="string"),
                    IOField(name="context", type="json", required=False),
                ],
                outputs=[
                    IOField(name="intent", type="string"),
                    IOField(name="entities", type="json"),
                    IOField(name="confidence", type="number"),
                    IOField(name="suggested_action", type="string"),
                ],
                tools=["llm.classify", "regex.patterns", "telemetry.emit"],
                notes="Must include correlate_id in upstream envelope."
            ),
            AgentSpec(
                name="PolicyAwarePlanner",
                purpose="Choose next step per policy (quiet hours, consent, caps).",
                inputs=[
                    IOField(name="intent", type="string"),
                    IOField(name="state", type="json"),
                    IOField(name="policy", type="json"),
                    IOField(name="timing", type="string"),
                ],
                outputs=[
                    IOField(name="decision", type="string"),  # send|wait|deny
                    IOField(name="channel", type="string", required=False),
                    IOField(name="when", type="string", required=False),
                    IOField(name="template_id", type="string", required=False),
                ],
                tools=["policy.guard", "scheduler.window", "telemetry.emit"],
                notes="Only component allowed to decide policy_denied."
            ),
        ],
        skills_coverage={
            "F1": ["ContentGenerator"],
            "F2": ["ReplyInterpreter", "PolicyAwarePlanner"],
        },
    )

# Convenience for CLIs or quick inspection
if __name__ == "__main__":
    print(get_catalog().model_dump_json(indent=2))
