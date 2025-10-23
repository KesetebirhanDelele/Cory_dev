import asyncio, os, asyncpg, time

async def main():
    dsn = os.getenv("DATABASE_URL")
    print("DSN:", dsn)
    t0=time.time()
    conn = await asyncpg.connect(dsn=dsn, timeout=45)  # allow 45s for first SSL handshake
    print("connected in %.2fs" % (time.time()-t0))
    row = await conn.fetchrow("select now() as now, current_user as usr")
    print(dict(row))
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
