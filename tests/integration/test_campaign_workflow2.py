# tests/integration/test_campaign_workflow.py
import copy
from app.orchestrator.temporal.common.instruction import Instruction
from app.orchestrator.temporal.workflows.campaign import plan_single_step

def test_single_step_returns_attempt_and_await_spec_sms():
    instr = Instruction(
        action="SendSMS",
        payload={"lead_id": "L1", "text": "Hello!"},
        await_timeout_seconds=45,
    )
    attempt, await_spec = plan_single_step(instr, state={"stage": "greeting"})

    # Attempt basics
    assert attempt.action == "SendSMS"
    assert attempt.params["text"] == "Hello!"

    # Await contract
    assert await_spec.expect == "delivered"
    assert await_spec.timeout_seconds == 45
    assert await_spec.on_timeout == "timeout"

def test_single_step_is_deterministic_no_io():
    instr = Instruction(
        action="StartCall",
        payload={"lead_id": "L2", "script_id": "S1"},
        await_timeout_seconds=30,
    )
    state = {"stage": "call_intro", "policy": {"quiet_hours": False}}

    a1, w1 = plan_single_step(instr, state)
    # Deep copy to ensure purity (no mutation of inputs)
    instr_copy = copy.deepcopy(instr)
    state_copy = copy.deepcopy(state)
    a2, w2 = plan_single_step(instr_copy, state_copy)

    # Determinism: identical outputs for identical inputs
    assert a1.model_dump() == a2.model_dump()
    assert w1.model_dump() == w2.model_dump()

def test_unknown_action_defaults_to_delivered_expectation():
    instr = Instruction(action="CustomActionX", payload={"foo": "bar"}, await_timeout_seconds=10)
    attempt, await_spec = plan_single_step(instr, state={})

    assert attempt.action == "CustomActionX"
    assert await_spec.expect == "delivered"   # safe default success expectation
    assert await_spec.timeout_seconds == 10
