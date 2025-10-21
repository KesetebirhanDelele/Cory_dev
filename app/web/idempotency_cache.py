# app/web/idempotency_cache.py
import asyncio
from cachetools import TTLCache

class IdempotencyCache:
    """Simple in-memory idempotency cache with TTL."""

    def __init__(self, ttl_seconds: int = 300, maxsize: int = 1000):
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = asyncio.Lock()

    async def reserve(self, key: str) -> bool:
        """Return True if key is new and reserved; False if duplicate."""
        async with self._lock:
            if key in self._cache:
                return False
            self._cache[key] = True
            return True

    def count(self, key: str | None = None) -> int:
        """Return count of all keys, or 1 if a specific key exists."""
        if key is None:
            return len(self._cache)
        return 1 if key in self._cache else 0

    def clear(self):
        """Clear all entries from cache (used in tests)."""
        self._cache.clear()

    def __len__(self):
        return len(self._cache)
