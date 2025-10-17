from app.orchestrator.langgraph.nodes.instruction_node import make_instruction

def test_make_instruction_sms():
    job = {"enrollment_id": "E1", "next_channel": "sms", "current_step_id": "S1", "campaign_id": "C1"}
    instr = make_instruction(job)
    assert instr.action == "SendSMS"
    assert instr.payload["enrollment_id"] == "E1"
    assert instr.payload["step_id"] == "S1"
    assert instr.payload["campaign_id"] == "C1"

def test_make_instruction_email():
    job = {"enrollment_id": "E2", "next_channel": "email", "current_step_id": "S2", "campaign_id": "C2"}
    instr = make_instruction(job)
    assert instr.action == "SendEmail"
    assert instr.payload["template"] == "intro"

def test_make_instruction_voice():
    job = {"enrollment_id": "E3", "next_channel": "voice", "current_step_id": "S3", "campaign_id": "C3"}
    instr = make_instruction(job)
    assert instr.action == "StartCall"
    assert instr.payload["agent_id"] == "followup_agent"

def test_make_instruction_unknown_channel():
    job = {"enrollment_id": "E4", "next_channel": "fax"}
    instr = make_instruction(job)
    assert instr.action == "noop"
