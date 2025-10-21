# app/web/idempotency.py
import asyncio
import time
from typing import Dict

class IdempotencyCache:
    """
    Async in-memory idempotency store.
    provider_ref -> expiry_ts
    Use reserve(provider_ref) to atomically check-and-reserve.
    """
    def __init__(self, ttl_seconds: int = 300):
        self._ttl = ttl_seconds
        self._store: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, provider_ref: str) -> bool:
        """Atomically reserve provider_ref. Return True if reserved (new); False if duplicate."""
        now = time.time()
        async with self._lock:
            expiry = self._store.get(provider_ref)
            if expiry is not None and expiry > now:
                return False
            self._store[provider_ref] = now + self._ttl
            return True

    async def is_reserved(self, provider_ref: str) -> bool:
        now = time.time()
        async with self._lock:
            expiry = self._store.get(provider_ref)
            if expiry is None:
                return False
            if expiry > now:
                return True
            del self._store[provider_ref]
            return False

    async def cleanup(self) -> None:
        """Optional: remove expired keys (call periodically if needed)."""
        now = time.time()
        async with self._lock:
            expired = [k for k,v in self._store.items() if v <= now]
            for k in expired:
                del self._store[k]
