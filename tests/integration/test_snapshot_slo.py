import asyncio
import os
import pytest

SLO_SECONDS = int(os.getenv("SNAPSHOT_SLO_SECONDS", "8"))
POLL_INTERVAL = 0.2  # seconds


async def _refresh_snapshot_with_pool(pool):
    """Call the RPC in a separate connection so MV sees committed rows."""
    async with pool.acquire() as conn:
        await conn.execute("select public.rpc_refresh_enrollment_state_snapshot();")


async def _assert_state_within_slo(pool, enrollment_id: str, expected: str):
    deadline = asyncio.get_event_loop().time() + SLO_SECONDS
    last = None
    while asyncio.get_event_loop().time() < deadline:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "select delivery_state "
                "from dev_nexus.enrollment_state_snapshot "
                "where enrollment_id=$1;",
                enrollment_id,
            )
        last = row["delivery_state"] if row else None
        if last == expected:
            return
        await asyncio.sleep(POLL_INTERVAL)
    assert last == expected, f"expected '{expected}' within {SLO_SECONDS}s, got '{last}'"


@pytest.mark.asyncio
async def test_snapshot_updates_within_slo(asyncpg_pool):
    # Use a dedicated connection for seeding/writes
    async with asyncpg_pool.acquire() as conn:
        proj_id = (await conn.fetchrow(
            "insert into dev_nexus.project(name, tenant_id) "
            "values('p', gen_random_uuid()) returning id;"
        ))["id"]

        camp_id = (await conn.fetchrow(
            "insert into dev_nexus.campaign(project_id, name) "
            "values($1, 'C') returning id;", proj_id
        ))["id"]

        ctc_id = (await conn.fetchrow(
            "insert into dev_nexus.contact(project_id, full_name, email) "
            "values($1, 'T User', concat(gen_random_uuid(),'@x.com')) returning id;",
            proj_id
        ))["id"]

        enr_id = (await conn.fetchrow(
            "insert into dev_nexus.enrollment(project_id, campaign_id, contact_id) "
            "values($1,$2,$3) returning id;",
            proj_id, camp_id, ctc_id
        ))["id"]

        # Insert an inbound completion -> delivered
        await conn.execute(
            "insert into dev_nexus.campaign_activity "
            "(enrollment_id, campaign_id, contact_id, channel, status, result_summary, created_at, completed_at) "
            "values ($1, $2, $3, 'sms', 'completed', 'completed', now(), now());",
            enr_id, camp_id, ctc_id
        )

    # Trigger refresh on a separate connection
    await _refresh_snapshot_with_pool(asyncpg_pool)

    # Assert MV state within SLO
    await _assert_state_within_slo(asyncpg_pool, enr_id, "delivered")


@pytest.mark.asyncio
async def test_mapping_policy_denied_and_timeout(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        proj_id = (await conn.fetchrow(
            "insert into dev_nexus.project(name, tenant_id) "
            "values('p2', gen_random_uuid()) returning id;"
        ))["id"]

        camp_id = (await conn.fetchrow(
            "insert into dev_nexus.campaign(project_id, name) "
            "values($1, 'C2') returning id;", proj_id
        ))["id"]

        ctc_id = (await conn.fetchrow(
            "insert into dev_nexus.contact(project_id, full_name, email) "
            "values($1, 'P User', concat(gen_random_uuid(),'@x.com')) returning id;",
            proj_id
        ))["id"]

        enr_id = (await conn.fetchrow(
            "insert into dev_nexus.enrollment(project_id, campaign_id, contact_id) "
            "values($1,$2,$3) returning id;",
            proj_id, camp_id, ctc_id
        ))["id"]

        # policy_denied flag → policy_denied
        await conn.execute(
            "insert into dev_nexus.campaign_activity "
            "(enrollment_id, campaign_id, contact_id, channel, status, result_summary, result_payload, created_at) "
            "values ($1, $2, $3, 'email', 'in_progress', 'in_progress', "
            "'{\"policy_denied\": true}'::jsonb, now());",
            enr_id, camp_id, ctc_id
        )

    await _refresh_snapshot_with_pool(asyncpg_pool)
    await _assert_state_within_slo(asyncpg_pool, enr_id, "policy_denied")

    # no_answer → timeout (wins over status)
    async with asyncpg_pool.acquire() as conn:
        await conn.execute(
            "insert into dev_nexus.campaign_activity "
            "(enrollment_id, campaign_id, contact_id, channel, status, result_summary, created_at) "
            "values ($1, $2, $3, 'voice', 'failed', 'no_answer', now());",
            enr_id, camp_id, ctc_id
        )

    await _refresh_snapshot_with_pool(asyncpg_pool)
    await _assert_state_within_slo(asyncpg_pool, enr_id, "timeout")


@pytest.mark.asyncio
async def test_mapping_failed(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        proj_id = (await conn.fetchrow(
            "insert into dev_nexus.project(name, tenant_id) "
            "values('p3', gen_random_uuid()) returning id;"
        ))["id"]

        camp_id = (await conn.fetchrow(
            "insert into dev_nexus.campaign(project_id, name) "
            "values($1, 'C3') returning id;", proj_id
        ))["id"]

        ctc_id = (await conn.fetchrow(
            "insert into dev_nexus.contact(project_id, full_name, email) "
            "values($1, 'F User', concat(gen_random_uuid(),'@x.com')) returning id;",
            proj_id
        ))["id"]

        enr_id = (await conn.fetchrow(
            "insert into dev_nexus.enrollment(project_id, campaign_id, contact_id) "
            "values($1,$2,$3) returning id;",
            proj_id, camp_id, ctc_id
        ))["id"]

        await conn.execute(
            "insert into dev_nexus.campaign_activity "
            "(enrollment_id, campaign_id, contact_id, channel, status, result_summary, created_at) "
            "values ($1, $2, $3, 'sms', 'failed', 'failed', now());",
            enr_id, camp_id, ctc_id
        )

    await _refresh_snapshot_with_pool(asyncpg_pool)
    await _assert_state_within_slo(asyncpg_pool, enr_id, "failed")
