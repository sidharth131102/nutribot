"""Meal-plan PDF rendering -- the only file allowed to import reportlab.

Renders a computed plan (the exact dict `plan_builder.build_plan` produces
and the frontend card displays) into a printable A4 document: cover
header, profile line, targets and the verified weekly summary, one table
per day with per-meal subtotals, the daily routine, a disclaimer, and
"Page x of y" footers. Every number comes straight from the plan dict --
nothing is recomputed here except the visual subtotals, which are sums of
the same items.

Pure: bytes out, no I/O, no LLM, no DB.
"""
from datetime import date
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.agents.plan_builder import macro_summary_line, plan_averages

ACCENT = colors.HexColor("#1f8f6f")
HEADER_BG = colors.HexColor("#e6f4ef")
ROW_ALT = colors.HexColor("#f6f9f8")
GRID = colors.HexColor("#c9d6d1")
MUTED = colors.HexColor("#5b6b66")

DISCLAIMER = (
    "This plan is generated from your profile and a curated food database for general nutrition "
    "guidance. It is not medical advice. Please review it with your doctor or a registered dietitian "
    "before making significant dietary changes, especially if you have a medical condition."
)


class _NumberedCanvas(pdf_canvas.Canvas):
    """Two-pass canvas so every footer can say 'Page x of y'."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 (reportlab API)
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        width, _ = A4
        self.setFont("Helvetica", 8)
        self.setFillColor(MUTED)
        self.drawString(18 * mm, 10 * mm, "NutriBot - personalised meal plan")
        self.drawRightString(width - 18 * mm, 10 * mm, f"Page {self._pageNumber} of {total}")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=20, textColor=ACCENT, spaceAfter=2 * mm),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontSize=10, textColor=MUTED, alignment=TA_CENTER, spaceAfter=6 * mm),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, textColor=ACCENT, spaceBefore=5 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9.5, leading=13),
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=8.5, leading=11, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=10.5),
        "cell_bold": ParagraphStyle("cell_bold", parent=base["Normal"], fontSize=8.5, leading=10.5, fontName="Helvetica-Bold"),
    }


def _fmt(value: Any, digits: int = 0) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:.{digits}f}"


def _profile_line(profile: dict[str, Any]) -> str:
    def _pretty(v: Any) -> str:
        return str(v).replace("_", " ") if v else ""

    parts = [
        f"Goal: {_pretty(profile.get('goal')) or 'n/a'}",
        f"Diet: {_pretty(profile.get('diet_type')) or 'n/a'}",
        f"Activity: {_pretty(profile.get('activity_level')) or 'n/a'}",
    ]
    conditions = ", ".join(profile.get("medical_conditions") or [])
    allergies = ", ".join(profile.get("allergies") or [])
    if conditions:
        parts.append(f"Conditions: {conditions}")
    if allergies:
        parts.append(f"Allergies: {allergies}")
    return "  |  ".join(parts)


def _targets_table(plan: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    targets = plan.get("macro_targets") or {}
    avg = plan_averages(plan)
    rows = [
        ["", "Calories", "Protein", "Carbs", "Fat"],
        [
            "Daily target",
            f"{_fmt(plan.get('calorie_target'))} kcal",
            f"{_fmt(targets.get('protein_g'))} g",
            f"{_fmt(targets.get('carbs_g'))} g",
            f"{_fmt(targets.get('fat_g'))} g",
        ],
        [
            "Weekly average",
            f"{_fmt(avg['calories'])} kcal",
            f"{_fmt(avg['protein'])} g",
            f"{_fmt(avg['carbs'])} g",
            f"{_fmt(avg['fat'])} g",
        ],
    ]
    table = Table(rows, colWidths=[38 * mm, 32 * mm, 28 * mm, 28 * mm, 28 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (1, 1), (-1, -1), "Helvetica", 9),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _day_block(day: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    totals = day.get("daily_totals") or {}
    heading = Paragraph(
        f"{day.get('day', 'Day')} &mdash; {_fmt(totals.get('calories'))} kcal "
        f"<font color='#5b6b66' size='9'>(protein {_fmt(totals.get('protein'))} g &middot; "
        f"carbs {_fmt(totals.get('carbs'))} g &middot; fat {_fmt(totals.get('fat'))} g)</font>",
        styles["h2"],
    )

    header = ["Meal", "Food", "Quantity", "kcal", "Protein", "Carbs", "Fat"]
    rows: list[list[Any]] = [header]
    style_cmds: list[tuple] = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]

    for meal in day.get("meals") or []:
        items = meal.get("items") or []
        if not items:
            continue
        first_row = len(rows)
        for item in items:
            rows.append([
                "",
                Paragraph(str(item.get("food", "")), styles["cell"]),
                str(item.get("quantity", "")),
                _fmt(item.get("calories")),
                f"{_fmt(item.get('protein'), 1)} g",
                f"{_fmt(item.get('carbs'), 1)} g",
                f"{_fmt(item.get('fat'), 1)} g",
            ])
        last_row = len(rows) - 1
        rows[first_row][0] = Paragraph(str(meal.get("name", "Meal")), styles["cell_bold"])
        style_cmds.append(("SPAN", (0, first_row), (0, last_row)))
        # Subtotal row per meal, from the plan's own meal total.
        rows.append(["", Paragraph("<i>Meal total</i>", styles["cell"]), "", _fmt(meal.get("total_calories")), "", "", ""])
        style_cmds.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), ROW_ALT))
        style_cmds.append(("LINEABOVE", (1, len(rows) - 1), (-1, len(rows) - 1), 0.6, ACCENT))

    rows.append([
        Paragraph("<b>Day total</b>", styles["cell_bold"]), "", "",
        _fmt(totals.get("calories")),
        f"{_fmt(totals.get('protein'), 1)} g",
        f"{_fmt(totals.get('carbs'), 1)} g",
        f"{_fmt(totals.get('fat'), 1)} g",
    ])
    style_cmds.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), HEADER_BG))
    style_cmds.append(("FONT", (0, len(rows) - 1), (-1, len(rows) - 1), "Helvetica-Bold", 8.5))

    table = Table(rows, colWidths=[27 * mm, 58 * mm, 20 * mm, 16 * mm, 18 * mm, 18 * mm, 17 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(style_cmds))
    return [KeepTogether([heading, table]), Spacer(1, 3 * mm)]


def render_meal_plan_pdf(
    plan: dict[str, Any],
    *,
    user_name: str,
    bot_name: str,
    profile: dict[str, Any] | None = None,
    generated_on: date | None = None,
) -> bytes:
    """Render the plan to PDF bytes. Raises ValueError if the plan has no days."""
    days = plan.get("days") or []
    if not days:
        raise ValueError("The plan has no days to render.")

    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"Meal plan for {user_name}",
        author=f"NutriBot ({bot_name})",
    )

    generated_on = generated_on or date.today()
    story: list[Any] = [
        Paragraph(f"{len(days)}-Day Meal Plan", styles["title"]),
        Paragraph(
            f"Prepared for <b>{user_name}</b> by {bot_name} &middot; {generated_on.strftime('%d %B %Y')}",
            styles["subtitle"],
        ),
    ]
    if profile:
        story.append(Paragraph(_profile_line(profile), styles["small"]))
        story.append(Spacer(1, 3 * mm))

    story.append(Paragraph("Targets and weekly summary", styles["h2"]))
    story.append(_targets_table(plan, styles))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(macro_summary_line(plan), styles["small"]))

    for day in days:
        story.extend(_day_block(day, styles))

    routine = (plan.get("daily_routine") or "").strip()
    if routine:
        story.append(Paragraph("Daily routine", styles["h2"]))
        story.append(Paragraph(routine.replace("\n", "<br/>"), styles["body"]))

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(DISCLAIMER, styles["small"]))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
