"""FastAPI application entry point — NutriBot API."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import bcrypt as _bcrypt

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.email_agent import deliver_plan_email
from backend.agents.graph import run_chat_pipeline
from backend.agents.memory_agent import save_accepted_plan
from backend.auth.google_oauth import exchange_code_for_token, get_google_user_info
from backend.auth.jwt_handler import create_access_token, get_current_user_id
from backend.config import get_settings
from backend.db.mongo import (
    append_messages,
    close_client,
    create_user,
    get_session_messages,
    get_user_by_email,
    get_user_by_google_id,
    get_user_by_id,
    get_accepted_plans,
    update_user,
)
from backend.models.chat import ChatRequest, ChatResponse, HistoryResponse
from backend.models.plan import PlanAcceptRequest, PlanAcceptResponse
from backend.models.user import (
    LoginRequest,
    ProfileCreateRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nutribot")


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password[:72].encode(), _bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password[:72].encode(), hashed.encode())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("NutriBot API starting up…")
    yield
    await close_client()
    logger.info("NutriBot API shut down.")


settings = get_settings()

app = FastAPI(
    title="NutriBot API",
    version="2.0.0",
    description="Production-grade AI nutrition assistant — 8-agent LangGraph pipeline",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── /api/health ───────────────────────────────────────────────────────────────

@app.get("/api/health/ping")
async def ping():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── /api/auth ─────────────────────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest):
    existing = await get_user_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    password_hash = _hash_password(payload.password)
    user_doc = {
        "email": payload.email,
        "full_name": payload.full_name,
        "password_hash": password_hash,
        "google_id": None,
        "profile_complete": False,
        "bot_name": "Nova",
        "medical_conditions": [],
        "allergies": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    user_id = await create_user(user_doc)
    token = create_access_token(user_id, payload.email)

    user_doc["id"] = user_id
    return TokenResponse(
        access_token=token,
        user=UserPublic(**{k: v for k, v in user_doc.items() if k in UserPublic.model_fields}),
    )


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    user = await get_user_by_email(payload.email)
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not _verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(
        access_token=token,
        user=UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields}),
    )


@app.get("/api/auth/google-callback")
async def google_callback(code: str = Query(...), state: str = Query(default="")):
    """Exchange Google OAuth code for a JWT token."""
    redirect_uri = f"{settings.frontend_url}/auth/google/callback"
    try:
        token_data = await exchange_code_for_token(code, redirect_uri)
        google_user = await get_google_user_info(token_data["access_token"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Google OAuth failed: {exc}") from exc

    google_id = google_user.get("id") or google_user.get("sub")
    email = google_user.get("email", "")
    full_name = google_user.get("name", email.split("@")[0])

    # Try to find existing user by google_id or email
    user = await get_user_by_google_id(google_id) or await get_user_by_email(email)
    if not user:
        user_doc = {
            "email": email,
            "full_name": full_name,
            "password_hash": None,
            "google_id": google_id,
            "profile_complete": False,
            "bot_name": "Nova",
            "medical_conditions": [],
            "allergies": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        user_id = await create_user(user_doc)
        user_doc["id"] = user_id
        user = user_doc
    elif not user.get("google_id"):
        await update_user(user["id"], {"google_id": google_id})

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(
        access_token=token,
        user=UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields}),
    )


# ── /api/profile ──────────────────────────────────────────────────────────────

@app.post("/api/profile/create", response_model=UserPublic)
async def create_profile(
    payload: ProfileCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    updates = payload.model_dump()
    updates["profile_complete"] = True
    await update_user(user_id, updates)

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields})


@app.get("/api/profile/me", response_model=UserPublic)
async def get_my_profile(user_id: str = Depends(get_current_user_id)):
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields})


@app.put("/api/profile/update", response_model=UserPublic)
async def update_profile(
    payload: ProfileUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        await update_user(user_id, updates)

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields})


# ── /api/chat ─────────────────────────────────────────────────────────────────

@app.post("/api/chat/message", response_model=ChatResponse)
async def chat_message(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    if payload.user_id != user_id:
        raise HTTPException(status_code=403, detail="User ID mismatch")

    # Verify profile is complete
    user = await get_user_by_id(user_id)
    if not user or not user.get("profile_complete"):
        raise HTTPException(
            status_code=400,
            detail="Profile not complete. Please complete your profile first.",
        )

    result = await run_chat_pipeline(
        user_id=user_id,
        session_id=payload.session_id,
        user_message=payload.message,
    )

    # Persist messages to MongoDB
    now = datetime.utcnow().isoformat()
    await append_messages(
        user_id,
        payload.session_id,
        [
            {"role": "user", "content": payload.message, "timestamp": now},
            {"role": "assistant", "content": result.get("response", ""), "timestamp": now},
        ],
    )

    return ChatResponse(
        response=result.get("response", ""),
        intent=result.get("intent", "GENERAL_CONVERSATION"),
        plan_proposed=result.get("plan_proposed", False),
        proposed_plan=result.get("proposed_plan"),
        session_id=payload.session_id,
    )


@app.get("/api/chat/history", response_model=HistoryResponse)
async def chat_history(
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
):
    messages_raw = await get_session_messages(user_id, session_id, limit=50)
    from backend.models.chat import ChatMessage
    messages = [
        ChatMessage(
            role=m.get("role", "user"),
            content=m.get("content", ""),
            timestamp=datetime.fromisoformat(m["timestamp"]) if "timestamp" in m else datetime.utcnow(),
        )
        for m in messages_raw
    ]
    return HistoryResponse(session_id=session_id, messages=messages)


# ── /api/plans ────────────────────────────────────────────────────────────────

@app.post("/api/plans/accept", response_model=PlanAcceptResponse)
async def accept_plan(
    payload: PlanAcceptRequest,
    user_id: str = Depends(get_current_user_id),
):
    if payload.user_id != user_id:
        raise HTTPException(status_code=403, detail="User ID mismatch")

    # Agent 7: save plan to MongoDB
    plan_id = await save_accepted_plan(
        user_id=user_id,
        plan_data=payload.plan_data,
        calorie_target=payload.calorie_target,
        plan_summary=payload.plan_summary,
    )

    # Agent 8: send email
    user = await get_user_by_id(user_id)
    email_sent = False
    if user:
        email_sent = await deliver_plan_email(
            user_email=user.get("email", ""),
            user_name=(user.get("full_name") or "").split()[0] or "there",
            bot_name=user.get("bot_name", "Nova"),
            meal_plan=payload.plan_data,
        )

    confirmation = (
        f"I've sent your meal plan to {user.get('email')}. Check your inbox! 📩"
        if email_sent
        else "Your meal plan has been saved!"
    )

    return PlanAcceptResponse(
        status="ok",
        plan_id=plan_id,
        message=confirmation,
    )


@app.get("/api/plans/saved")
async def get_saved_plans(user_id: str = Depends(get_current_user_id)):
    plans = await get_accepted_plans(user_id)
    return {"plans": plans}
