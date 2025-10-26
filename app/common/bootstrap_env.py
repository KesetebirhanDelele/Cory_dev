# app/common/bootstrap_env.py
from __future__ import annotations
import os

# Try to load .env from repo root (or wherever you keep it)
try:
    from dotenv import load_dotenv, find_dotenv  # pip install python-dotenv
    # Only fill missing vars; don’t overwrite ones already set in the shell/CI
    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception as e:
    # Safe no-op if python-dotenv isn’t installed
    if os.getenv("DEBUG_ENV_BOOTSTRAP") == "1":
        print(f"[env] dotenv not loaded: {e}")
