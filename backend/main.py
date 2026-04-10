import logging
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.graph import generate_plan
from backend.database import engine, get_session
from backend.models import Base, Plan, User
from backend.schemas import (
    ChatRequest,
    CreateUserProfileRequest,
    GeneratePlanRequest,
    GeneratePlanResponse,
    SavePlanRequest,
    UserProfileResponse,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nutribot")

app = FastAPI(title="NutriBot API", version="0.1.0")


@app.on_event("startup")
async def startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.post("/generate-plan", response_model=GeneratePlanResponse)
async def generate_plan_endpoint(payload: GeneratePlanRequest) -> GeneratePlanResponse:
    try:
        return await generate_plan(payload.user_profile, payload.query or "Generate a meal plan.")
    except RuntimeError as exc:
        logger.exception("generation configuration error")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("generation failed")
        raise HTTPException(status_code=500, detail="meal generation failed") from exc


@app.post("/chat", response_model=GeneratePlanResponse)
async def chat_endpoint(payload: ChatRequest) -> GeneratePlanResponse:
    return await generate_plan_endpoint(
        GeneratePlanRequest(user_profile=payload.user_profile, query=payload.message)
    )


@app.get("/user-profile", response_model=UserProfileResponse)
async def get_user_profile(
    user_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
) -> UserProfileResponse:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return UserProfileResponse.model_validate(user)


@app.post("/save-plan")
async def save_plan(
    payload: SavePlanRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int | str]:
    user = await session.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    totals = payload.plan.daily_totals
    plan = Plan(
        user_id=payload.user_id,
        date=date.today(),
        calories=totals.calories,
        protein=totals.protein,
        carbs=totals.carbs,
        fat=totals.fat,
        plan_json=payload.plan.model_dump(mode="json"),
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return {"status": "ok", "plan_id": plan.id}


@app.post("/user-profile", response_model=UserProfileResponse)
async def create_user_profile(
    payload: CreateUserProfileRequest,
    session: AsyncSession = Depends(get_session),
) -> UserProfileResponse:
    profile = payload.user_profile
    user = User(**profile.model_dump(mode="json"))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserProfileResponse.model_validate(user)


@app.get("/health")
async def health() -> dict[str, str]:
    async with engine.begin() as session:
        await session.execute(select(1))
    return {"status": "ok"}
