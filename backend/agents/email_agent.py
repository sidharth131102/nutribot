"""Agent 8 — Email Delivery Agent (Tool-Calling).

Triggered after Agent 7 saves an accepted plan. Sends the formatted
meal plan to the user's registered email via SendGrid.

This agent runs from the /api/plans/accept endpoint, NOT the main pipeline.
"""
import logging
from typing import Any

from backend.tools.email_tool import send_meal_plan_email

logger = logging.getLogger("nutribot.agent.email")


async def deliver_plan_email(
    user_email: str,
    user_name: str,
    bot_name: str,
    meal_plan: dict[str, Any],
) -> bool:
    """Send the accepted meal plan to the user's email.

    Returns True if the email was delivered successfully.
    """
    logger.info("Sending meal plan email to %s", user_email)
    success = await send_meal_plan_email(
        user_email=user_email,
        user_name=user_name,
        bot_name=bot_name,
        meal_plan=meal_plan,
    )
    if success:
        logger.info("Email delivered to %s", user_email)
    else:
        logger.warning("Email delivery failed for %s", user_email)
    return success
