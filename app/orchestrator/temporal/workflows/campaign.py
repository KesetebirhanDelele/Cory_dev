from dataclasses import dataclass
from datetime import timedelta
from temporalio import workflow as wf

@dataclass
class WFState:
    enrollment_id: str
    delivered: bool = False
    attempts: int = 0
    last_status: str | None = None

@wf.defn
class CampaignWorkflow:
    def __init__(self) -> None:
        self.s = WFState(enrollment_id="")

    @wf.signal
    async def provider_event(self, status: str):
        self.s.last_status = status
        if status in ("delivered", "completed", "answered"):
            self.s.delivered = True

    @wf.run
    async def run(self, enrollment_id: str, action: str, payload: dict, policy: dict):
        from app.orchestrator.temporal.activities.sms_send import run as sms_send
        from app.orchestrator.temporal.activities.email_send import run as email_send
        from app.orchestrator.temporal.activities.voice_start import run as voice_start
        from app.orchestrator.temporal.activities.interactions_log import log as interactions_log
        from app.orchestrator.temporal.activities.handoff_create import run as handoff_create

        self.s.enrollment_id = enrollment_id

        while self.s.attempts < policy.get("max_attempts", 3) and not self.s.delivered:
            self.s.attempts += 1

            if action == "send_sms":
                await wf.execute_activity(sms_send, enrollment_id, payload, start_to_close_timeout=timedelta(seconds=20))
            elif action == "send_email":
                await wf.execute_activity(email_send, enrollment_id, payload, start_to_close_timeout=timedelta(seconds=20))
            elif action == "send_voice":
                await wf.execute_activity(voice_start, enrollment_id, payload, start_to_close_timeout=timedelta(seconds=30))

            await wf.execute_activity(interactions_log, enrollment_id, action, start_to_close_timeout=timedelta(seconds=10))

            ok = await wf.wait_condition(lambda: self.s.delivered, timeout=timedelta(minutes=policy.get("await_minutes", 5)))
            if not ok:
                await wf.sleep(timedelta(minutes=policy.get("backoff_minutes", 2)))

        if not self.s.delivered and policy.get("escalate"):
            await wf.execute_activity(handoff_create, enrollment_id, "attempts_exhausted", start_to_close_timeout=timedelta(seconds=20))
