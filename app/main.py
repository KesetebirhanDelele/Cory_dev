# main.py
import asyncio
import importlib
import logging
import os
import random
import signal
import time
from typing import Callable, Optional

from fastapi import FastAPI
from app.web.webhook import router as webhook_router

app = FastAPI(title="Cory API")

# Mount the webhook routes
app.include_router(webhook_router)

# Optional: load .env if present
try:
    from dotenv import load_dotenv  # pip install python-dotenv
    load_dotenv()
except Exception:
    pass

# ---- Config (env overrides) -------------------------------------------------
ACTIONS_INTERVAL_SEC   = int(os.getenv("ACTIONS_INTERVAL_SEC", "60"))   # v_due_actions → route work
SMS_INTERVAL_SEC       = int(os.getenv("SMS_INTERVAL_SEC", "30"))       # v_due_sms_followups → send
VOICE_INTERVAL_SEC     = int(os.getenv("VOICE_INTERVAL_SEC", "60"))     # due voice actions
CALLPROC_INTERVAL_SEC  = int(os.getenv("CALLPROC_INTERVAL_SEC", "30"))  # process phone_call_logs_stg

# Enable/disable individual loops quickly via env
ENABLE_ORCHESTRATOR = os.getenv("ENABLE_ORCHESTRATOR", "1") == "1"
ENABLE_SMS_SENDER   = os.getenv("ENABLE_SMS_SENDER", "1") == "1"
ENABLE_VOICE_DIALER = os.getenv("ENABLE_VOICE_DIALER", "0") == "1"  # off by default until provider wired
ENABLE_CALL_PROC    = os.getenv("ENABLE_CALL_PROC", "1") == "1"

# Backend selection for DB helpers (your repo has both styles available)
DB_BACKEND = os.getenv("DB_BACKEND", "asyncpg").lower()  # "asyncpg" | "supabase"

# Timeout for a single tick, to prevent hung calls
TICK_TIMEOUT_SEC = int(os.getenv("TICK_TIMEOUT_SEC", "45"))

# Jitter applied to sleep (e.g., 0.2 => +/-20% interval variability)
SLEEP_JITTER = float(os.getenv("SLEEP_JITTER", "0.15"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


# ---- Helpers ----------------------------------------------------------------
def get_callable(mod_name: str, candidates: list[str]) -> Optional[Callable]:
    """
    Import a module and return the first existing function by name.
    Returns None if module or function isn't found.
    """
    try:
        mod = importlib.import_module(mod_name)
    except Exception:
        logging.debug("Module not found or failed import: %s", mod_name)
        return None
    for fn_name in candidates:
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            logging.info("Bound %s.%s", mod_name, fn_name)
            return fn
    logging.debug("No callable matched in %s: %s", mod_name, candidates)
    return None


async def jittered_sleep(seconds: float, jitter: float) -> None:
    if seconds <= 0:
        return
    if jitter > 0:
        factor = random.uniform(1 - jitter, 1 + jitter)
        seconds *= factor
    await asyncio.sleep(seconds)


async def worker_loop(name: str, tick: Callable[[], "asyncio.Future"], interval: int) -> None:
    """
    Generic loop with timeout, exponential backoff on errors, and jittered sleep.
    The tick() must be an async callable that performs one unit of work.
    """
    backoff = 1.0
    while True:
        start = time.monotonic()
        try:
            # Run a single tick with a timeout
            await asyncio.wait_for(tick(), timeout=TICK_TIMEOUT_SEC)
            # Reset backoff on success
            backoff = 1.0
        except asyncio.TimeoutError:
            logging.warning("[%s] tick timed out after %ss", name, TICK_TIMEOUT_SEC)
            backoff = min(backoff * 2, 60.0)
            await asyncio.sleep(backoff)
            continue
        except Exception as ex:
            logging.exception("[%s] tick failed: %s", name, ex)
            backoff = min(backoff * 2, 60.0)
            await asyncio.sleep(backoff)
            continue

        # Sleep until next interval (minus time already spent), with jitter
        elapsed = time.monotonic() - start
        await jittered_sleep(max(0.0, interval - elapsed), SLEEP_JITTER)


# ---- Optional DB pool init (asyncpg path) -----------------------------------
async def maybe_init_db():
    if DB_BACKEND == "asyncpg":
        try:
            from app.data.db import init_db_pool  # your asyncpg pool initializer
            await init_db_pool()
            logging.info("Initialized asyncpg pool.")
        except Exception as ex:
            logging.exception("Failed to init asyncpg pool: %s", ex)
            raise
    else:
        logging.info("DB_BACKEND=%s (no pool init needed).", DB_BACKEND)


# ---- Compose the runnable ticks from your repo ------------------------------
def build_ticks():
    """
    Returns a list of (name, coroutine, interval).
    We detect functions across your modules to avoid hard crashes if something isn't ready yet.
    """
    ticks: list[tuple[str, Callable, int]] = []

    # Orchestrator: decides next actions for enrollments (v_due_actions)
    if ENABLE_ORCHESTRATOR:
        orch_tick = get_callable(
            "orchestrator_graph",
            ["run_orchestrator_once", "run_orchestrator_tick", "run_orchestrator"]
        )
        if orch_tick:
            ticks.append(("orchestrator", orch_tick, ACTIONS_INTERVAL_SEC))
        else:
            logging.warning("Orchestrator not found; skipping.")

    # SMS sender: picks up planned SMS from v_due_sms_followups
    if ENABLE_SMS_SENDER:
        sms_tick = get_callable("sms_sender", ["run_sms_sender"])
        if sms_tick:
            ticks.append(("sms_sender", sms_tick, SMS_INTERVAL_SEC))
        else:
            logging.warning("SMS sender not found; skipping.")

    # Voice dialer: attempts outbound calls for due voice actions
    if ENABLE_VOICE_DIALER:
        voice_tick = get_callable("voice_dialer", ["run_voice_dialer", "run_voice_dialer_once"])
        if voice_tick:
            ticks.append(("voice_dialer", voice_tick, VOICE_INTERVAL_SEC))
        else:
            logging.warning("Voice dialer not found; skipping.")

    # Call processing: applies policy to new call logs in staging
    if ENABLE_CALL_PROC:
        callproc_tick = get_callable(
            "call_processing_agent",
            ["run_call_processing_once", "run_call_processing", "process_staging_once"]
        )
        if callproc_tick:
            ticks.append(("call_processing", callproc_tick, CALLPROC_INTERVAL_SEC))
        else:
            logging.warning("Call processing agent not found; skipping.")

    return ticks


# ---- Graceful shutdown -------------------------------------------------------
class GracefulExit(SystemExit):
    pass


def _handle_sig():
    raise GracefulExit()


async def _main():
    # Logging setup
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    logging.info("Starting Cory main...")

    # Init DB if needed
    await maybe_init_db()

    # Build ticks
    ticks = build_ticks()
    if not ticks:
        logging.error("No agents enabled/found. Set ENABLE_* envs or add modules.")
        return

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _handle_sig)
        except NotImplementedError:
            # Windows / restricted envs may not support this; ignore
            pass

    # Spawn workers
    tasks: list[asyncio.Task] = []
    for name, tick, interval in ticks:
        # Stagger initial starts a bit to avoid thundering herd
        async def starter(n=name, t=tick, i=interval, delay=random.uniform(0, 2.0)):
            await asyncio.sleep(delay)
            await worker_loop(n, t, i)

        tasks.append(asyncio.create_task(starter(), name=f"{name}_task"))

    logging.info("Running %d agent loop(s): %s", len(tasks), [t.get_name() for t in tasks])

    # Wait for termination
    try:
        await asyncio.gather(*tasks)
    except GracefulExit:
        logging.info("Shutdown signal received; cancelling tasks...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        logging.info("Cory main stopped.")


if __name__ == "__main__":
    asyncio.run(_main())
