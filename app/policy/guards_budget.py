# app/policy/guards_budget.py
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

class BudgetDenied(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


# -----------------------------------------------------------
# Atomic checks
# -----------------------------------------------------------

def check_budget(campaign_spent: float, campaign_limit: float | None) -> None:
    """Block if total campaign spend exceeds its budget."""
    if campaign_limit is not None and campaign_spent >= campaign_limit:
        raise BudgetDenied("budget_cap", "Campaign budget exceeded")


def check_rate(count_last_hour: int, hourly_limit: int | None) -> None:
    """Block if send count in the last hour exceeds the rate cap."""
    if hourly_limit is not None and count_last_hour >= hourly_limit:
        raise BudgetDenied("rate_cap", "Hourly rate limit reached")


# -----------------------------------------------------------
# Async orchestrator helper
# -----------------------------------------------------------

async def evaluate_budget_caps(
    db, campaign_id: str, channel: str, policy: Dict[str, Any]
) -> Tuple[bool, str, Dict[str, Any] | None]:
    """
    Called before channel activity dispatch.
    Enforces per-campaign and per-channel caps.
    Returns (allowed, reason, hint)
    """
    try:
        # --- Query aggregated campaign spend / send counts ------------------
        q_budget = """
            SELECT COALESCE(SUM(cost_usd),0) AS spent
            FROM interactions
            WHERE campaign_id = $1
        """
        q_rate = """
            SELECT COUNT(*) AS cnt
            FROM interactions
            WHERE campaign_id = $1 AND channel = $2
              AND created_at > (NOW() - INTERVAL '1 hour')
        """
        res_budget = await db.execute_query(q_budget, campaign_id)
        res_rate = await db.execute_query(q_rate, campaign_id, channel)

        spent = float(res_budget[0].get("spent", 0) if res_budget else 0)
        count_last_hour = int(res_rate[0].get("cnt", 0) if res_rate else 0)

    except Exception as e:
        logger.warning("BudgetCapQueryError", extra={"error": str(e)})
        return True, "allowed", None

    limit_budget = policy.get("budget_usd_limit")
    limit_hourly = policy.get("rate_limit_per_hour")

    try:
        check_budget(spent, limit_budget)
        check_rate(count_last_hour, limit_hourly)
        return True, "allowed", None

    except BudgetDenied as e:
        hint: Dict[str, Any] = {}
        if e.code == "budget_cap":
            hint = {"action": "pause_campaign"}
        elif e.code == "rate_cap":
            hint = {"retry_in_minutes": 60}

        logger.info(
            "BudgetOrRateBlocked",
            extra={
                "campaign_id": campaign_id,
                "channel": channel,
                "reason": e.code,
                "hint": hint,
                "spent": spent,
                "limit_budget": limit_budget,
                "count_last_hour": count_last_hour,
                "limit_hourly": limit_hourly,
            },
        )
        return False, e.code, hint
