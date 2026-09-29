"""Filter food_db.json items based on user profile constraints."""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal

from backend.config import get_settings
from backend.models.user import DietType

# Mirrors backend/tools/calorie_tool.py's DEFAULT_MACRO_SPLIT — the food list
# offered to the model should span the same macro balance its targets assume,
# not skew to one macro and cap how many calories a plan can physically reach.
MACRO_SELECTION_SPLIT: dict[str, float] = {"protein": 0.30, "carb": 0.40, "fat": 0.30}

# Map spec DietType values → food_db.json diet_types values
DIET_TYPE_MAP: dict[str, str] = {
    DietType.vegetarian: "veg",
    DietType.vegan: "vegan",
    DietType.non_vegetarian: "non_veg",
}

# Conditions that require low GI foods
LOW_GI_CONDITIONS = {"diabetes", "pcos", "type 2 diabetes", "type2 diabetes"}

LOW_GI_VALUES = {"low", "very_low"}


@lru_cache(maxsize=1)
def _load_food_db() -> list[dict[str, Any]]:
    path = Path(get_settings().food_db_path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalize(values: Iterable[str]) -> set[str]:
    return {v.strip().lower().replace("-", " ").replace("_", " ") for v in values}


def _dominant_macro(food: dict[str, Any]) -> Literal["protein", "carb", "fat"]:
    """Classify a food by which macro contributes the most calories."""
    protein_cal = float(food.get("protein", 0)) * 4
    carb_cal = float(food.get("carbs", 0)) * 4
    fat_cal = float(food.get("fat", 0)) * 9
    top = max(protein_cal, carb_cal, fat_cal)
    if top == protein_cal:
        return "protein"
    if top == carb_cal:
        return "carb"
    return "fat"


def _is_condition_safe(food: dict[str, Any], conditions: set[str]) -> bool:
    tags = set(food.get("medical_tags", []))
    gi = (food.get("glycemic_index") or "").lower()

    if "diabetes" in conditions or "type 2 diabetes" in conditions:
        if gi not in LOW_GI_VALUES and "diabetes_safe" not in tags:
            return False

    if "hypertension" in conditions or "high blood pressure" in conditions:
        if "high_sodium" in tags or "hypertension_avoid" in tags:
            return False

    if "kidney disease" in conditions or "ckd" in conditions or "kidney" in conditions:
        if "kidney_avoid" in tags:
            return False
        if float(food.get("protein", 0)) > 25 and "controlled_protein" not in tags:
            return False

    return True


_CHEAT_DAY_RE = re.compile(r"\bcheat\s*(day|meal)s?\b", re.IGNORECASE)


def wants_cheat_day(user_message: str) -> bool:
    """Whether the user's message asks for a cheat day/meal. Deterministic
    keyword match, not an LLM call, for the same reason _requested_day_count
    (backend/agents/meal_plan_agent.py) is: cheap, instant, and testable in
    isolation. Shared by food_agent_node (widens the food pool) and
    meal_plan_agent (picks which day and how to phrase the selection rule)."""
    return bool(_CHEAT_DAY_RE.search(user_message or ""))


def wants_cheat_day_in_conversation(user_message: str, chat_history: list[dict[str, Any]] | None) -> bool:
    """wants_cheat_day(), but sticky across a modification conversation.

    A cheat day is usually requested once ("...with one cheat day") and then
    refined over several follow-up turns ("use fries instead", "make it
    spicier") that never repeat the words "cheat day" -- checking only the
    current message made the system silently forget the cheat day existed
    the moment the conversation moved past the turn that first asked for it,
    dropping every treat food from the plan with no explanation. Only USER
    turns are scanned (the assistant's own phrasing, e.g. "Day 7 is your
    cheat day", shouldn't be what re-triggers this every subsequent turn).
    Naturally bounded by the session's chat_history window -- a new chat
    session starts with empty history, so this doesn't leak across
    unrelated conversations."""
    if wants_cheat_day(user_message):
        return True
    for msg in chat_history or []:
        if msg.get("role") != "user":
            continue
        content = msg.get("content_en") or msg.get("content") or ""
        if wants_cheat_day(content):
            return True
    return False


TREAT_TAG = "treat"
# Reserved slots for treat-tagged items when include_treats=True. A fixed
# count (not a share of `limit`) so a cheat day reliably gets real indulgent
# options regardless of `limit`, while every other call's food list length
# and composition stays byte-for-byte unchanged (include_treats defaults to
# False, and when False treat items never enter `filtered` at all -- a
# regular week can never surface pizza or ice cream just because the general
# selection algorithm happened to have room).
TREAT_RESERVED_SLOTS = 16


def get_filtered_foods(
    user_profile: dict[str, Any],
    meal_type: str | None = None,
    limit: int = 80,
    include_treats: bool = False,
) -> list[dict[str, Any]]:
    """Return foods filtered and ranked for the given user profile.

    Filtering (diet type, allergens, medical conditions, GI) is absolute and
    happens first. Selection then reserves a share of `limit` per meal slot
    (SLOT_SHARE) and balances macros within each slot (_select_balanced), so
    the list handed to the model can physically reach the calorie target at
    every meal of the day.

    `include_treats` is for a cheat day: it lifts the (otherwise absolute)
    exclusion of treat-tagged foods and reserves TREAT_RESERVED_SLOTS of the
    result for them, on top of the normal slot-aware selection -- diet type,
    allergens, and medical-condition safety still apply to treats exactly as
    they do to every other food, so a cheat day can never surface someone's
    allergen or violate a medical exclusion, it only widens which *otherwise
    safe* foods are on the table.

    Args:
        user_profile: The full user profile dict.
        meal_type: Optional filter by meal type (breakfast/lunch/dinner/snack).
        limit: Maximum number of foods to return.
        include_treats: Whether to include treat-tagged (indulgent) foods.

    Returns:
        List of food dicts from food_db.json that pass all filters.
    """
    foods = _load_food_db()
    diet_type_raw = user_profile.get("diet_type", "")
    diet_key = DIET_TYPE_MAP.get(diet_type_raw, diet_type_raw)

    allergies = _normalize(user_profile.get("allergies", []))
    conditions = _normalize(user_profile.get("medical_conditions", []))
    needs_low_gi = bool(LOW_GI_CONDITIONS.intersection(conditions))

    filtered: list[dict[str, Any]] = []
    treats: list[dict[str, Any]] = []
    for food in foods:
        is_treat = TREAT_TAG in {t.lower() for t in food.get("tags", [])}
        if is_treat and not include_treats:
            continue

        # Diet type check
        food_diets = {d.lower() for d in food.get("diet_types", [])}
        if diet_key not in food_diets:
            continue

        # Allergen check (absolute)
        food_allergens = _normalize(food.get("allergens", []))
        if allergies.intersection(food_allergens):
            continue

        # Medical condition safety (absolute)
        if not _is_condition_safe(food, conditions):
            continue

        # Meal type filter (optional)
        if meal_type:
            food_meal_types = {m.lower() for m in food.get("meal_types", [])}
            if meal_type.lower() not in food_meal_types:
                continue

        # Low GI enforcement for diabetics/PCOS -- still applies to treats:
        # a cheat day relaxes food "purity", never a medical safety bound.
        if needs_low_gi:
            gi = (food.get("glycemic_index") or "").lower()
            if gi and gi not in LOW_GI_VALUES and gi != "medium":
                continue

        (treats if is_treat else filtered).append(food)

    # An explicit meal_type filter means the caller wants one slot's foods,
    # so the per-slot quota pass below would be meaningless -- just balance.
    if meal_type:
        pool = filtered + treats
        return _select_balanced(pool, limit, needs_low_gi)

    reserved_treats = _select_balanced(treats, TREAT_RESERVED_SLOTS, needs_low_gi) if include_treats else []
    reserved_ids = {f["id"] for f in reserved_treats}
    remaining_limit = max(limit - len(reserved_treats), 0)

    # Slot-aware selection. Before this, a single macro-balanced pass over
    # the whole list handed a non-veg muscle-gain profile 19 lunch/dinner
    # foods, 2 breakfast foods and 1 snack food -- 7 breakfasts and 14
    # snacks a week had to come from paneer, tofu scramble and tuna, and
    # every day undershot the calorie target by 25-35% because there was
    # nothing calorie-dense to fill the small meals with.
    selected: list[dict[str, Any]] = []
    seen: set[str] = set(reserved_ids)
    for slot, share in SLOT_SHARE.items():
        quota = round(remaining_limit * share)
        candidates = [
            f for f in filtered
            if f["id"] not in seen and slot in {m.lower() for m in f.get("meal_types", [])}
        ]
        for food in _select_balanced(candidates, quota, needs_low_gi):
            selected.append(food)
            seen.add(food["id"])

    # Slot quotas that couldn't be filled (a niche profile with few breakfast
    # foods, say) leave room -- top up from whatever is left, still balanced.
    if len(selected) < remaining_limit:
        remaining = [f for f in filtered if f["id"] not in seen]
        selected.extend(_select_balanced(remaining, remaining_limit - len(selected), needs_low_gi))

    return (reserved_treats + selected)[:limit]


# Share of the list reserved for each meal slot. Lunch and dinner overlap
# almost entirely in food_db.json, so their combined share is effectively one
# main-meal pool; breakfast and snacks are the slots that used to starve.
SLOT_SHARE: dict[str, float] = {"breakfast": 0.25, "snack": 0.20, "lunch": 0.275, "dinner": 0.275}

# Carb foods at or above this density are "staples" (grains, roti, oats,
# makhana); below it they're produce (vegetables, fruit). Both belong in a
# plan, but only staples let a day reach its calorie target.
STAPLE_MIN_KCAL_PER_100G = 100.0


def _kcal_per_100g(food: dict[str, Any]) -> float:
    grams = float(food.get("quantity_grams") or 0)
    return float(food.get("calories", 0)) / grams * 100 if grams > 0 else 0.0


def _interleave(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], ratio: int = 2) -> list[dict[str, Any]]:
    """`ratio` items from primary, then one from secondary, repeat; leftovers appended."""
    out: list[dict[str, Any]] = []
    p, s = 0, 0
    while p < len(primary) or s < len(secondary):
        for _ in range(ratio):
            if p < len(primary):
                out.append(primary[p])
                p += 1
        if s < len(secondary):
            out.append(secondary[s])
            s += 1
    return out


def _select_balanced(candidates: list[dict[str, Any]], n: int, needs_low_gi: bool) -> list[dict[str, Any]]:
    """Pick up to `n` foods across protein/carb/fat pools per MACRO_SELECTION_SPLIT.

    A flat protein-first ranking used to exclude carb/fat foods entirely from
    a small `limit` (issue #12), and even after pooling by dominant macro the
    *within-pool* ranking was still protein-first -- so the "carb" pool was
    all dals and the "fat" pool all seeds, never oats/roti/rice/oils. Carb
    and fat pools now rank by calorie density (with a 2:1 staple:produce
    interleave for carbs so vegetables and fruit still appear); only the
    protein pool ranks by protein.
    """
    if n <= 0 or not candidates:
        return []

    def _gi(food: dict[str, Any]) -> int:
        # Low-GI-first ordering only matters for profiles that need it; for
        # everyone else it just pushed medium-GI staples like oats to the back.
        if not needs_low_gi:
            return 0
        return 0 if food.get("glycemic_index") in LOW_GI_VALUES else 1

    pools: dict[str, list[dict[str, Any]]] = {"protein": [], "carb": [], "fat": []}
    for food in candidates:
        pools[_dominant_macro(food)].append(food)

    pools["protein"].sort(key=lambda f: (_gi(f), -float(f.get("protein", 0))))
    pools["fat"].sort(key=lambda f: (_gi(f), -_kcal_per_100g(f)))
    staples = sorted(
        (f for f in pools["carb"] if _kcal_per_100g(f) >= STAPLE_MIN_KCAL_PER_100G),
        key=lambda f: (_gi(f), -_kcal_per_100g(f)),
    )
    produce = sorted(
        (f for f in pools["carb"] if _kcal_per_100g(f) < STAPLE_MIN_KCAL_PER_100G),
        key=lambda f: (_gi(f), -float(f.get("protein", 0))),
    )
    pools["carb"] = _interleave(staples, produce)

    allocation = {k: round(n * v) for k, v in MACRO_SELECTION_SPLIT.items()}
    selected: list[dict[str, Any]] = []
    remaining_slots = n
    for i, category in enumerate(allocation):
        pool = pools[category]
        is_last = i == len(allocation) - 1
        take = min(len(pool), remaining_slots) if is_last else min(len(pool), allocation[category])
        selected.extend(pool[:take])
        pools[category] = pool[take:]
        remaining_slots -= take

    # A pool ran out -- top up round-robin from the others so the shortfall
    # doesn't all land in one macro.
    while remaining_slots > 0 and any(pools.values()):
        for category in allocation:
            if remaining_slots > 0 and pools[category]:
                selected.append(pools[category].pop(0))
                remaining_slots -= 1

    return selected[:n]


def format_food_context(foods: list[dict[str, Any]]) -> str:
    """Format filtered foods as a readable string for the LLM prompt."""
    if not foods:
        return "No approved foods available."
    lines = ["APPROVED FOOD OPTIONS (use ONLY these items):"]
    lines.append(
        f"{'ID':<10} {'Food':<35} {'g':>5} {'kcal':>6} {'P':>5} {'C':>5} {'F':>5} {'Meal Types'}"
    )
    lines.append("-" * 100)
    for f in foods:
        lines.append(
            f"{f['id']:<10} {f['food']:<35} {f['quantity_grams']:>5} "
            f"{f['calories']:>6} {f['protein']:>5} {f['carbs']:>5} {f['fat']:>5} "
            f"{', '.join(f.get('meal_types', []))}"
        )
    return "\n".join(lines)


_PAREN_SUFFIX = re.compile(r"\s*\([^)]*\)")


def _strip_qualifier(name: str) -> str:
    """'turkey breast (cooked)' -> 'turkey breast' — for tolerant name matching."""
    return _PAREN_SUFFIX.sub("", name).strip().lower()


def food_name_matches(candidate: str, food_context: list[dict[str, Any]]) -> bool:
    """Whether a model-generated food name reasonably matches an approved food.

    Tolerant on purpose: the model may drop a parenthetical qualifier or phrase
    a name slightly differently while still meaning an approved item. Used both
    to enforce the allow-list in production (meal_plan_agent._sanitize_plan) and
    to score it in the eval harness — kept in one place so they can't drift.
    """
    candidate_norm = _strip_qualifier(candidate)
    candidate_id = candidate.strip().lower()
    if not candidate_norm:
        return False

    return find_food(candidate, food_context) is not None


def find_food(candidate: str, food_context: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The approved food a model-generated name refers to, or None.

    Same tolerance as food_name_matches (this is what it's built on). Exact
    name/id matches win over substring matches so "dal" resolves to "dal",
    not "masoor dal (cooked)" -- the plan builder computes every nutrient
    from the returned entry, so which entry wins actually matters.
    """
    candidate_norm = _strip_qualifier(candidate)
    candidate_id = candidate.strip().lower()
    if not candidate_norm:
        return None

    partial: dict[str, Any] | None = None
    for food in food_context:
        allowed_norm = _strip_qualifier(food.get("food", ""))
        allowed_id = str(food.get("id", "")).strip().lower()
        if not allowed_norm:
            continue
        if candidate_norm == allowed_norm or candidate_id == allowed_id:
            return food
        if partial is None and (candidate_norm in allowed_norm or allowed_norm in candidate_norm):
            partial = food

    return partial
