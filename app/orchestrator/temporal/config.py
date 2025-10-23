# app/orchestrator/temporal/config.py
import os

# Where the Temporal frontend is reachable
TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")

# Which namespace to use
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")

# Queue name both the worker listens on and tests use
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "cory-handoff-queue")

# === C5.1 additions ===
AI_MATCH_QUEUE = "ai-match-q" # task queue for program/persona matching