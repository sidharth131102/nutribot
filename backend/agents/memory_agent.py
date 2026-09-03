"""Agent 7 — Plan Memory Agent.

Triggered when the user explicitly accepts a proposed meal plan.
Saves the plan to MongoDB under the user's accepted_plans, enforcing
the 2-plan maximum limit. Older plans are evicted automatically.

This agent runs from the /api/plans/accept endpoint, NOT from the
main chat LangGraph pipeline.
"""
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.db.mongo import UserScopedRepo, get_db

logger = logging.getLogger("nutribot.agent.memory")


async def save_accepted_plan(
    user_id: str,
    plan_data: dict[str, Any],
    calorie_target: float,
    plan_summary: str,
) -> str:
    """Persist an accepted plan and return the new plan_id."""
    plan_doc = {
        "plan_id": str(uuid4()),
        "accepted_at": datetime.utcnow().isoformat(),
        "calorie_target": calorie_target,
        "plan_summary": plan_summary,
        "plan_full": plan_data,
    }

    repo = UserScopedRepo(get_db(), user_id)
    await repo.save_accepted_plan(plan_doc)
    logger.info("Plan %s saved for user %s", plan_doc["plan_id"], user_id)
    return plan_doc["plan_id"]
