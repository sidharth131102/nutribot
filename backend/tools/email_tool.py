"""SendGrid / SMTP email delivery tool for meal plan distribution."""
import logging
from typing import Any

from backend.config import get_settings

logger = logging.getLogger("nutribot.email")


def _build_html_email(
    user_name: str,
    bot_name: str,
    meal_plan: dict[str, Any],
) -> str:
    """Generate an HTML email body for the meal plan."""
    days_html = ""
    for day in meal_plan.get("days", []):
        day_label = day.get("day", "Day")
        meals_html = ""
        for meal in day.get("meals", []):
            items_rows = "".join(
                f"<tr><td style='padding:4px 8px'>{item['food']}</td>"
                f"<td style='padding:4px 8px'>{item['quantity']}</td>"
                f"<td style='padding:4px 8px'>{item['calories']} kcal</td>"
                f"<td style='padding:4px 8px'>{item['protein']}g P | {item['carbs']}g C | {item['fat']}g F</td></tr>"
                for item in meal.get("items", [])
            )
            meals_html += f"""
            <h4 style='color:#20c997;margin:12px 0 4px'>{meal['name']} — {meal['total_calories']} kcal</h4>
            <table style='border-collapse:collapse;width:100%;font-size:13px'>
              <thead><tr style='background:#1a2e2a'>
                <th style='padding:4px 8px;text-align:left'>Food</th>
                <th style='padding:4px 8px;text-align:left'>Quantity</th>
                <th style='padding:4px 8px;text-align:left'>Calories</th>
                <th style='padding:4px 8px;text-align:left'>Macros</th>
              </tr></thead>
              <tbody>{items_rows}</tbody>
            </table>"""

        totals = day.get("daily_totals", {})
        days_html += f"""
        <div style='background:#101a18;border:1px solid #25413b;border-radius:8px;padding:16px;margin-bottom:16px'>
          <h3 style='color:#edf7f4;margin:0 0 8px'>{day_label}</h3>
          {meals_html}
          <p style='margin-top:12px;font-size:13px;color:#9fb8b1'>
            Daily totals — {totals.get('calories',0)} kcal |
            Protein {totals.get('protein',0)}g |
            Carbs {totals.get('carbs',0)}g |
            Fat {totals.get('fat',0)}g
          </p>
        </div>"""

    routine = meal_plan.get("daily_routine", "")
    routine_section = (
        f"<h2 style='color:#20c997'>Daily Routine</h2>"
        f"<p style='color:#edf7f4;white-space:pre-line'>{routine}</p>"
        if routine
        else ""
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset='utf-8'></head>
<body style='background:#0b1110;font-family:Inter,sans-serif;color:#edf7f4;padding:32px'>
  <div style='max-width:720px;margin:0 auto'>
    <div style='text-align:center;margin-bottom:32px'>
      <h1 style='color:#20c997;margin:0'>🥗 NutriBot</h1>
      <p style='color:#9fb8b1;margin-top:4px'>Your Personalized Nutrition Plan from {bot_name}</p>
    </div>

    <p>Hi <strong>{user_name}</strong>,</p>
    <p style='color:#9fb8b1'>
      Here is your 7-day personalized meal plan, crafted specifically for your health goals
      and dietary preferences. Remember to stay hydrated and listen to your body!
    </p>

    <h2 style='color:#20c997'>Your 7-Day Meal Plan</h2>
    {days_html}

    {routine_section}

    <div style='border-top:1px solid #25413b;margin-top:32px;padding-top:16px;text-align:center'>
      <p style='color:#9fb8b1;font-size:12px'>
        ⚠️ Please consult your doctor or registered dietitian before making significant dietary changes,
        especially if you have an existing medical condition.<br><br>
        Sent with ❤️ by <strong>{bot_name}</strong> · NutriBot AI Nutrition Assistant
      </p>
    </div>
  </div>
</body>
</html>"""


async def send_meal_plan_email(
    user_email: str,
    user_name: str,
    bot_name: str,
    meal_plan: dict[str, Any],
) -> bool:
    """Send the meal plan email via SendGrid. Returns True on success."""
    settings = get_settings()
    if not settings.sendgrid_api_key:
        logger.warning("SENDGRID_API_KEY not set — skipping email delivery")
        return False

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content

        sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
        html_body = _build_html_email(user_name, bot_name, meal_plan)

        message = Mail(
            from_email=Email(settings.email_from, settings.email_from_name),
            to_emails=To(user_email),
            subject=f"Your Personalized Meal Plan from {bot_name} 🥗",
            html_content=Content("text/html", html_body),
        )

        response = sg.client.mail.send.post(request_body=message.get())
        success = response.status_code in (200, 202)
        if success:
            logger.info("Meal plan email sent to %s", user_email)
        else:
            logger.error(
                "SendGrid returned status %s for %s", response.status_code, user_email
            )
        return success
    except Exception as exc:
        logger.exception("Failed to send email to %s: %s", user_email, exc)
        return False
