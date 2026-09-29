"""One-off script: renders the cheat-meals knowledge-base document as a PDF
into data/, matching the other RAG source PDFs (diabetes_guidelines.pdf,
pcos_nutrition.pdf, ...). Run once with `python scripts/build_cheat_meals_pdf.py`,
then re-run `python -m backend.rag.ingest` to pick it up into Pinecone + the
local BM25 corpus.

Not part of the app itself -- this is a content-authoring tool, run by hand
whenever the guidance text changes, same as how the other guideline PDFs were
presumably authored/updated outside the codebase.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "cheat_meals_guidelines.pdf"

styles = getSampleStyleSheet()
title_style = ParagraphStyle("DocTitle", parent=styles["Title"], fontSize=18, spaceAfter=14)
h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=14, spaceBefore=14, spaceAfter=6)
h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10.5, leading=15, spaceAfter=8)
bullet = ParagraphStyle("Bullet", parent=body, leftIndent=14, bulletIndent=4, spaceAfter=4)

SECTIONS: list[tuple[str, str, list[str]]] = [
    (
        "What a Cheat Meal Is",
        "A cheat meal is a single meal, and a cheat day extends that to one full day, "
        "that is deliberately planned to be more indulgent than the rest of a person's "
        "regular eating pattern -- richer, less restricted, chosen more for enjoyment "
        "than for strict nutritional optimisation. Used well, it is a planned, bounded "
        "exception within an otherwise consistent plan, not a loss of control and not a "
        "reason to abandon the day's calorie target. The distinguishing feature of a "
        "well-handled cheat day is that it is still a *planned* part of the week, with "
        "its calories and macros accounted for like any other day, just built from more "
        "indulgent food choices.",
        [],
    ),
    (
        "Why People Include Cheat Meals",
        "The most consistent, well-supported reason to include a cheat meal is "
        "adherence: a rigid diet with zero flexibility is harder for most people to "
        "sustain over months, and an occasional planned indulgence can reduce the "
        "feeling of deprivation that leads to abandoning a plan altogether. Some people "
        "also report it helps with food-related cravings and social situations (a "
        "birthday, a family meal, a restaurant outing) without guilt derailing the rest "
        "of the week. Claims that a single cheat meal meaningfully changes metabolic "
        "rate or hormone levels are not well established and should not be used to "
        "justify a cheat meal on physiological grounds -- the honest reason to include "
        "one is sustainability and enjoyment, not a metabolic boost.",
        [],
    ),
    (
        "The Core Rule: Still Hits the Calorie Target",
        "A cheat day is not a free-for-all day. The single most important guidance in "
        "this document is that a cheat day should still land on the person's daily "
        "calorie target (with the same tolerance used on every other day of their "
        "plan) -- what changes is the *composition* of that budget, not its size. "
        "Within that same number of calories, the day leans toward more indulgent, "
        "less \"clean\" foods (a dessert, a fried item, a richer main course) instead of "
        "the whole-food staples used on a typical day. This keeps the day itself "
        "calorie-neutral relative to the plan while still giving genuine variety and "
        "enjoyment.",
        [],
    ),
    (
        "How to Build a Healthy Cheat Meal",
        "A cheat meal is healthier and more satisfying when it still keeps a few basic "
        "habits from a normal meal, even while leaning indulgent:",
        [
            "Include some protein at the meal -- it improves satiety and helps prevent "
            "the meal from being purely refined carbohydrate and fat.",
            "Eat slowly and pay attention -- rushing a cheat meal tends to lead to "
            "eating past the point of satisfaction without extra enjoyment.",
            "Pick one or two indulgent items to really enjoy rather than sampling many "
            "different rich foods at once, which makes portion awareness much harder.",
            "Stay hydrated -- a glass of water before and during the meal helps with "
            "portion awareness and digestion.",
            "Keep the rest of that day's meals (if it is a cheat day, not just a cheat "
            "meal) at their normal portions so the day's total still lands on target.",
        ],
    ),
    (
        "Frequency and Placement",
        "For most people pursuing a sustainable plan, one cheat meal or cheat day per "
        "week is a common and reasonable cadence -- frequent enough to support "
        "adherence, infrequent enough to stay a genuine exception rather than the norm. "
        "Placing it on a day with lower stress or higher activity (e.g. after a workout, "
        "or a planned social event) tends to work better than placing it on a low-"
        "activity, high-stress day. A cheat day should never be placed on back-to-back "
        "days, and a plan should never schedule more than one cheat day within a single "
        "week -- if a person wants more flexibility than that, the underlying calorie "
        "target itself should be reviewed, not the frequency of cheat days.",
        [],
    ),
    (
        "What to Avoid",
        "A cheat meal stops being a helpful, planned exception when it:",
        [
            "Exceeds the day's calorie target rather than reallocating it -- an "
            "over-target cheat day undoes the purpose of tracking the rest of the week.",
            "Involves an amount of alcohol that itself contributes a large, untracked "
            "number of calories or impairs the person's ability to stop at a planned "
            "portion.",
            "Becomes several indulgent meals in a row instead of one bounded meal or "
            "day -- this is a sign the plan's overall restriction may be too strict and "
            "worth revisiting rather than a sign the person lacks willpower.",
            "Includes a known personal allergen or a food excluded for a diagnosed "
            "medical reason. A cheat day changes how strict the *food choices* are, "
            "never the *safety* constraints -- allergies and medically necessary "
            "exclusions apply on a cheat day exactly as they do on every other day.",
        ],
    ),
    (
        "Special Considerations for Medical Conditions",
        "For diabetes, a cheat meal has a larger practical impact on blood glucose than "
        "it does for someone without diabetes, so pairing any indulgent carbohydrate "
        "with protein, fibre, or fat to slow absorption is worth extra attention, and "
        "portion size matters more than it does for other conditions. For PCOS, "
        "keeping the meal's overall glycemic load moderate (rather than eliminating "
        "indulgence entirely) is a reasonable middle ground. For hypertension, the "
        "main practical concern with many indulgent/restaurant-style foods is sodium "
        "content rather than calories -- choosing a rich dessert over a very salty "
        "savoury dish can be the easier trade-off. For thyroid conditions, there is no "
        "special restriction specific to a cheat meal beyond what already applies to "
        "the person's regular plan. In every case, this is general guidance, not "
        "medical advice -- a person managing a medical condition should confirm with "
        "their doctor or dietitian how much flexibility is appropriate for their "
        "specific situation.",
        [],
    ),
    (
        "Getting Back on Track",
        "A single cheat meal or cheat day has no meaningful effect on longer-term "
        "progress by itself; what matters is simply resuming the regular plan at the "
        "very next meal. There is no need to \"compensate\" with an unusually low-"
        "calorie day afterward -- that pattern (restrict, indulge, restrict harder) is "
        "less sustainable than treating the cheat day as already accounted for and "
        "moving on. The goal of a cheat day is to make the overall plan easier to "
        "stick with over months, not to be undone by guilt the next morning.",
        [],
    ),
]


def build() -> None:
    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title="Cheat Meals and Cheat Days: Guidelines",
    )
    story = [
        Paragraph("Cheat Meals and Cheat Days: Guidelines", title_style),
        Paragraph(
            "General nutrition guidance on including planned indulgent meals in an "
            "otherwise consistent eating plan.",
            body,
        ),
        Spacer(1, 6),
    ]
    for heading, intro, bullets in SECTIONS:
        story.append(Paragraph(heading, h1))
        story.append(Paragraph(intro, body))
        for b in bullets:
            story.append(Paragraph(f"- {b}", bullet))
    doc.build(story)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
