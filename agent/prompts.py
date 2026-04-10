from langchain_core.prompts import ChatPromptTemplate


MEAL_PLAN_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a strict nutrition planning engine. You only generate meal plans. "
            "You must not perform independent nutrition calculations. Use only USER CONTEXT allowed_foods values.",
        ),
        (
            "human",
            """USER CONTEXT:
{cag_context}

RETRIEVED KNOWLEDGE:
{rag_docs}

CRITICAL RULES:
- Follow all constraints strictly.
- Do not violate medical restrictions.
- You MUST ONLY use foods from USER CONTEXT allowed_foods.
- DO NOT invent new food items.
- DO NOT use foods outside the provided allowed_foods list.
- All macros must exactly match the provided allowed_foods values.
- The item quantity string must be "<quantity_grams> grams" from allowed_foods.
- Total calories must be within +/- 50 kcal of USER CONTEXT targets.calories.
- Protein must be greater than or equal to USER CONTEXT targets.protein.
- Fat must be 20-35% of total calories.
- Return 3-5 meals.
- Output ONLY valid JSON matching this schema:
{{
  "meals": [
    {{
      "name": "Breakfast",
      "items": [
        {{
          "food": "string",
          "quantity": "100 grams",
          "calories": 0,
          "protein": 0,
          "carbs": 0,
          "fat": 0
        }}
      ],
      "total_calories": 0
    }}
  ],
  "daily_totals": {{
    "calories": 0,
    "protein": 0,
    "carbs": 0,
    "fat": 0
  }}
}}

USER QUERY:
{query}
""",
        ),
    ]
)
