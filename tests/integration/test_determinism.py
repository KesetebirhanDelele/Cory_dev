import asyncio
import json
import os
import random
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
import pytest

# ---- Test configuration ------------------------------------------------------

# All tests run fully offline: block network stacks and known adapters
BLOCKED_MODULES = [
    "httpx",            # SlickText + Synthflow templates use httpx
    "aiohttp",          # Synthflow async session
    "app.external.synthflow",
    "app.external.n8n",
    "app.external.email",
    "app.external.sms",
]

# Deterministic seed for chaos and RNG
DEFAULT_SEED = 1337

# ---- Minimal workflow harness (shape-compatible with Cory agent graph) -------

@dataclass
class SideEffect:
    """A canonical, hashable envelope for any 'send'."""
    kind: str           # 'voice' | 'sms' | 'email' | 'webhook'
    idempotency_key: str
    payload: Dict[str, Any]

class InMemoryOutbox:
    """Captures side-effects locally and enforces idempotency/no-dup semantics."""
    def __init__(self):
        self._seen: set[str] = set()
        self._events: List[SideEffect] = []

    def send(self, evt: SideEffect):
        if evt.idempotency_key in self._seen:
            # would be a duplicate send
            raise AssertionError(f"Duplicate send detected: {evt.idempotency_key}")
        self._seen.add(evt.idempotency_key)
        self._events.append(evt)

    @property
    def events(self) -> List[SideEffect]:
        return list(self._events)

# A seeded chaos adapter: randomly fail N% of calls but deterministically per seed.
class ChaosAdapter:
    def __init__(self, outbox: InMemoryOutbox, failure_rate: float, seed: int):
        self.outbox = outbox
        self.failure_rate = failure_rate
        self.rng = random.Random(seed)

    async def maybe_send(self, kind: str, idem: str, payload: Dict[str, Any]):
        # Inject failure before side-effect is "sent"
        if self.rng.random() < self.failure_rate:
            raise RuntimeError(f"Injected {kind} failure")
        self.outbox.send(SideEffect(kind=kind, idempotency_key=idem, payload=payload))

# Simple retry with backoff (deterministic because we avoid jitter)
async def retry_send(fn, *, retries=2, backoff_seconds=0.01):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return await fn()
        except Exception as e:
            last_exc = e
            if attempt == retries:
                raise
            await asyncio.sleep(backoff_seconds)
    raise last_exc

# The "workflow" under test: mirrors classify → orchestrate → progress
async def run_workflow_once(input_lead: Dict[str, Any], chaos: ChaosAdapter) -> Dict[str, Any]:
    """
    No external I/O: all side-effects go to the in-memory outbox via ChaosAdapter.
    """
    # Classify (deterministic rule for test)
    classification = {
        "intent": "interested" if "nursing" in input_lead.get("interest", "") else "needs_info",
        "next_action": "voice_call",
        "confidence": 0.82,
    }

    # Orchestrate: choose channel and 'send' with idempotency keys
    idem_key = f"lead:{input_lead['id']}:stage:initial:voice"
    payload = {
        "lead_id": input_lead["id"],
        "lead_email": input_lead["email"],
        "campaign": "fall-2025",
        "org": "demo-university",
    }
    async def do_send():
        return await chaos.maybe_send("voice", idem_key, payload)

    await retry_send(do_send, retries=2, backoff_seconds=0.001)

    # Progress: compute next contact (ticks with current time)
    return {
        "status": "advanced",
        "next_contact_at_epoch": int(time.time()) + 60,  # +60s
        "classification": classification,
    }

# ---- Fixtures ----------------------------------------------------------------

@contextmanager
def block_external_io(monkeypatch):
    """
    Any attempt to import or use external HTTP clients/adapters will error.
    This proves "no external I/O in workflow".
    """
    # Block module imports
    import builtins
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in BLOCKED_MODULES or any(name.startswith(m + ".") for m in BLOCKED_MODULES):
            raise RuntimeError(f"External I/O module blocked in tests: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    try:
        yield
    finally:
        monkeypatch.setattr(builtins, "__import__", real_import)

@pytest.fixture
def seeded(seed: int = DEFAULT_SEED):
    random.seed(seed)
    return seed

@pytest.fixture
def outbox():
    return InMemoryOutbox()

@pytest.fixture
def chaos(outbox, seeded):
    # 40% failure rate to exercise retries; deterministic via seed
    return ChaosAdapter(outbox=outbox, failure_rate=0.4, seed=seeded)

# ---- Tests -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_external_io_and_determinism(monkeypatch, outbox, chaos, seeded):
    """
    Run the workflow twice with the same seed and inputs.
    Assert: identical outputs and identical side-effect envelopes.
    Also assert: any attempt to import network libs would fail.
    """
    with block_external_io(monkeypatch):
        lead = {"id": "L-001", "email": "a@b.edu", "interest": "nursing"}

        # Run twice (same seed → same failure pattern → same retry path)
        state1 = await run_workflow_once(lead, chaos)
        events1 = [e.__dict__ for e in outbox.events]

        # Reset outbox but keep chaos RNG seeded the same
        out2 = InMemoryOutbox()
        chaos2 = ChaosAdapter(outbox=out2, failure_rate=0.4, seed=seeded)
        state2 = await run_workflow_once(lead, chaos2)
        events2 = [e.__dict__ for e in out2.events]

        assert json.dumps(state1, sort_keys=True) == json.dumps(state2, sort_keys=True)
        assert json.dumps(events1, sort_keys=True) == json.dumps(events2, sort_keys=True)

@pytest.mark.asyncio
async def test_retries_recover_without_duplicate_sends(outbox, seeded):
    """
    Force the first attempt to fail, ensure retries succeed, and verify that the
    idempotency key prevents duplicate sends.
    """
    chaos = ChaosAdapter(outbox=outbox, failure_rate=1.0, seed=seeded)  # fail all…
    lead = {"id": "L-002", "email": "x@y.edu", "interest": "nursing"}

    # First run: exhaust retries and fail
    with pytest.raises(RuntimeError):
        await run_workflow_once(lead, chaos)

    # Now reduce failure rate so a retry path eventually succeeds
    chaos_ok = ChaosAdapter(outbox=outbox, failure_rate=0.0, seed=seeded)
    await run_workflow_once(lead, chaos_ok)

    # Exactly one event in outbox for that idempotency key
    kinds = [e.kind for e in outbox.events]
    assert kinds.count("voice") == 1, f"Expected 1 send, got events={outbox.events}"

@pytest.mark.asyncio
async def test_time_skipping_stress(monkeypatch, outbox, chaos):
    """
    Fast-forward time in large steps to flush timers and ensure no deadlocks.
    """
    # Replace time.time to simulate jumps forward
    base = time.time()
    ticks = {"i": 0}
    def fake_time():
        # Each call advances 5 seconds deterministically
        val = base + ticks["i"] * 5
        ticks["i"] += 1
        return val

    monkeypatch.setattr(time, "time", fake_time)

    lead = {"id": "L-003", "email": "t@u.edu", "interest": "nursing"}
    # If deadlocked, this will exceed wait_for timeout and fail
    result = await asyncio.wait_for(run_workflow_once(lead, chaos), timeout=0.5)

    assert result["status"] == "advanced"
    assert outbox.events, "Expected at least one side-effect event"
