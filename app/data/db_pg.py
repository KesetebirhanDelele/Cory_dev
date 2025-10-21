# app/data/db_pg.py
import os, asyncpg

_DSN = os.getenv("DATABASE_URL")
_pool = None

async def init_db_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=_DSN, min_size=1, max_size=5)
    return _pool

async def run_query(sql: str, *args):
    pool = _pool or await init_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]
