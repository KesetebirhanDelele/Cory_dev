# app/orchestrator/temporal/workflows/workflow_registry.py

"""
Central registry of all Temporal workflows.
The worker imports this list and assigns workflows to queues.
"""

from app.orchestrator.temporal.workflows.answer_builder import AnswerWorkflow
from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow
from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow
from app.orchestrator.temporal.workflows.program_match import ProgramMatchWf
from app.orchestrator.temporal.workflows.simulated_followup import SimulatedFollowupWorkflow
from app.orchestrator.temporal.workflows.followup_callback import CallbackFollowupWorkflow
from app.orchestrator.temporal.workflows.book_appointment_workflow import BookAppointmentWorkflow
from app.orchestrator.temporal.workflows.sms_direct_reply import SMSDirectReplyWorkflow


# --------------------------------------------------------------------------
# IMPORTANT:
# This list must include *every* workflow definition exactly once.
# Workers will select which workflows they use per queue.
# --------------------------------------------------------------------------
WORKFLOWS = [
    # Core campaign automation
    CampaignWorkflow,
    HandoffWorkflow,
    AnswerWorkflow,              # Used on RAG queue only
    CallbackFollowupWorkflow,
    BookAppointmentWorkflow,

    # SMS auto-reply workflow
    # SMSDirectReplyWorkflow,

    # Matching workflows (used on ai-match-q)
    ProgramMatchWf,

    # Simulated nurture/follow-up workflow (followup-q)
    SimulatedFollowupWorkflow,
]
