"""FastAPI application entry point — NutriBot API."""
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import bcrypt as _bcrypt
from bson import ObjectId

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from backend.agents.email_agent import deliver_plan_email
from backend.agents.graph import run_chat_pipeline, stream_chat_pipeline
from backend.agents.memory_agent import save_accepted_plan
from backend.auth.google_oauth import exchange_code_for_token, get_google_user_info
from backend.auth.jwt_handler import create_access_token, get_current_user_id
from backend.config import Settings, get_settings
from backend.db.mongo import (
    UserScopedRepo,
    close_client,
    create_user,
    ensure_indexes,
    get_db,
    get_user_by_email,
    get_user_by_google_id,
)
from backend.documents import doc_intelligence
from backend.documents.blob_storage import BlobStorageClient
from backend.documents.extraction import process_document
from backend.documents.validation import document_type_for, validate_upload
from backend.models.chat import ChatRequest, ChatResponse, HistoryResponse
from backend.models.consent import ConsentStatusResponse
from backend.models.medical_document import (
    DocumentBatchDeleteRequest,
    DocumentDeleteResponse,
    DocumentUploadResponse,
    MedicalDocumentSummary,
)
from backend.models.plan import PlanAcceptRequest, PlanAcceptResponse, PlanPdfRequest, WeeklyMealPlan
from backend.models.speech import SpeechTokenResponse, SpokenLanguagesResponse, SpokenLocale
from backend.models.user import (
    LoginRequest,
    ProfileCreateRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)
from backend.observability import configure_logging, configure_tracing, new_trace_id, trace_id_var
from backend.security.rate_limit import chat_message_rate_limit, login_rate_limit, register_rate_limit
from backend.speech import locales as speech_locales
from backend.speech import multilingual
from backend.speech import token as speech_token
from backend.tools.pdf_tool import render_meal_plan_pdf

MEDICAL_CONSENT_TYPE = "medical_data_processing"

configure_logging()
configure_tracing(get_settings())
logger = logging.getLogger("nutribot")


def _validate_production_secrets(settings: Settings) -> None:
    """Refuse to boot in production with missing/default-insecure config."""
    if settings.environment != "production":
        return

    problems = []
    if not settings.jwt_secret or settings.jwt_secret == "change-me-in-production":
        problems.append("JWT_SECRET is unset or using the insecure default")
    if "localhost" in settings.mongodb_uri or "127.0.0.1" in settings.mongodb_uri:
        problems.append("MONGODB_URI points at localhost in production")
    if not settings.groq_api_key:
        problems.append("GROQ_API_KEY is unset")
    if settings.llm_provider.startswith("azure_openai"):
        if not settings.azure_openai_api_key:
            problems.append("AZURE_OPENAI_API_KEY is unset")
        if not settings.azure_openai_endpoint:
            problems.append("AZURE_OPENAI_ENDPOINT is unset")
    if settings.llm_provider == "azure_openai_challenger":
        if not settings.azure_openai_challenger_deployment_full:
            problems.append("AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FULL is unset")
        if not settings.azure_openai_challenger_deployment_fast:
            problems.append("AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FAST is unset")
    if not settings.pinecone_api_key:
        problems.append("PINECONE_API_KEY is unset")
    if not settings.azure_storage_connection_string:
        problems.append("AZURE_STORAGE_CONNECTION_STRING is unset")
    if not settings.azure_doc_intelligence_api_key:
        problems.append("AZURE_DOC_INTELLIGENCE_API_KEY is unset")

    if problems:
        raise RuntimeError(
            "Refusing to start in production with insecure/missing config:\n- " + "\n- ".join(problems)
        )


_validate_production_secrets(get_settings())


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password[:72].encode(), _bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password[:72].encode(), hashed.encode())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("NutriBot API starting up…")
    # Verify MongoDB connection on startup
    try:
        from backend.db.mongo import get_client
        await get_client().admin.command("ping")
        logger.info("MongoDB connection OK")
        await ensure_indexes()
        logger.info("MongoDB indexes ensured")
    except Exception as exc:
        logger.error("MongoDB connection/index setup FAILED: %s", exc)
    yield
    await close_client()
    logger.info("NutriBot API shut down.")


settings = get_settings()
blob_client = BlobStorageClient(settings)

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
async def register(payload: RegisterRequest, _: None = Depends(register_rate_limit)):
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
async def login(payload: LoginRequest, _: None = Depends(login_rate_limit)):
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
        await UserScopedRepo(get_db(), user["id"]).update_user({"google_id": google_id})

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(
        access_token=token,
        user=UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields}),
    )


# ── /api/profile ──────────────────────────────────────────────────────────────

async def _require_medical_consent(repo: UserScopedRepo, medical_conditions: list | None) -> None:
    """Gate: writing non-empty medical_conditions requires current consent
    (roadmap: consent must be explicit, recorded, revocable, checked before
    medical data is processed or stored)."""
    if not medical_conditions:
        return
    status_doc = await repo.get_consent_status(MEDICAL_CONSENT_TYPE)
    if not status_doc["granted"]:
        raise HTTPException(
            status_code=403,
            detail="Medical data processing consent required before storing medical conditions. "
                   "Grant it via POST /api/consent/grant first.",
        )


@app.post("/api/profile/create", response_model=UserPublic)
async def create_profile(
    payload: ProfileCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    repo = UserScopedRepo(get_db(), user_id)
    await _require_medical_consent(repo, payload.medical_conditions)

    updates = payload.model_dump()
    updates["profile_complete"] = True
    await repo.update_user(updates)
    if payload.medical_conditions:
        await repo.log_access("medical_conditions_allergies", "write", trace_id_var.get())

    user = await repo.get_user()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields})


@app.get("/api/profile/me", response_model=UserPublic)
async def get_my_profile(user_id: str = Depends(get_current_user_id)):
    user = await UserScopedRepo(get_db(), user_id).get_user()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields})


@app.put("/api/profile/update", response_model=UserPublic)
async def update_profile(
    payload: ProfileUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    repo = UserScopedRepo(get_db(), user_id)
    await _require_medical_consent(repo, payload.medical_conditions)

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        if "goal" in updates:
            current = await repo.get_user()
            old_goal = current.get("goal") if current else None
            if old_goal and old_goal != updates["goal"]:
                await repo.add_episodic_event("goal_change", {"old_goal": old_goal, "new_goal": updates["goal"]})
        await repo.update_user(updates)
    if payload.medical_conditions:
        await repo.log_access("medical_conditions_allergies", "write", trace_id_var.get())

    user = await repo.get_user()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic(**{k: v for k, v in user.items() if k in UserPublic.model_fields})


# ── /api/chat ─────────────────────────────────────────────────────────────────

def _content_for_history(result: dict[str, Any]) -> str:
    """The text stored in `content_en` -- what gets replayed as pipeline
    context on every future turn (chat_memory_window messages, into two
    separate generation calls for a plan turn: see meal_plan_agent.py).

    A plan turn's full response is prose + an entire day-by-day table
    (easily 1,500-3,000+ tokens); replaying that verbatim on every later
    turn is how a session with a few plans in it snowballs into tens of
    thousands of tokens per turn. Only the table is dropped here -- the
    prose (personality, what was actually said) is kept so future turns
    still have real conversational continuity. `content` (the user-facing
    field, used to redisplay an old session) always keeps the full text;
    this only thins what the model itself re-reads.
    """
    response = result.get("response", "")
    parts = result.get("response_parts")
    if not parts:
        return response
    full = f"{parts['prose']}\n\n{parts['plan_markdown']}\n\n{parts['accept_prompt']}"
    if full != response:
        # The output guardrail replaced the response wholesale (regeneration
        # fallback) -- response_parts no longer describes it, don't trust it.
        return response

    plan = result.get("proposed_plan") or {}
    days = len(plan.get("days") or [])
    target = plan.get("calorie_target")
    marker = (
        f"(a {days}-day meal plan was generated here, ~{target:.0f} kcal/day target — full plan omitted from history)"
        if days and target
        else "(a meal plan was generated here — full plan omitted from history)"
    )
    return f"{parts['prose']}\n\n{marker}"


async def _finalize_chat_response(
    payload: ChatRequest,
    repo: UserScopedRepo,
    inbound: Any,
    result: dict[str, Any],
) -> ChatResponse:
    """Shared tail of both the plain and streaming chat endpoints: translate
    the pipeline's English result back to the user's language, persist both
    sides of the turn, and build the response payload. Both endpoints must
    return byte-for-byte the same ChatResponse shape, so this lives in one
    place rather than two copies that could quietly drift apart."""
    settings = get_settings()
    response_out = await multilingual.outbound(settings, result, inbound.language)

    # `content` is what the user saw (their own language), `content_en` is
    # what the pipeline processed -- the context builder feeds `content_en`
    # back into later turns.
    now = datetime.utcnow().isoformat()
    await repo.append_messages(
        payload.session_id,
        [
            {
                "role": "user",
                "content": payload.message,
                "content_en": inbound.english_text,
                "language": inbound.language,
                "timestamp": now,
            },
            {
                "role": "assistant",
                "content": response_out,
                "content_en": _content_for_history(result),
                "language": inbound.language,
                "timestamp": now,
            },
        ],
    )

    return ChatResponse(
        response=response_out,
        intent=result.get("intent", "GENERAL_CONVERSATION"),
        plan_proposed=result.get("plan_proposed", False),
        proposed_plan=result.get("proposed_plan"),
        session_id=payload.session_id,
        rag_sources=result.get("rag_sources", []),
        language=inbound.language,
        message_english=inbound.english_text if inbound.translated else None,
    )


async def _authorize_chat_request(payload: ChatRequest, user_id: str, repo: UserScopedRepo) -> None:
    if payload.user_id != user_id:
        raise HTTPException(status_code=403, detail="User ID mismatch")
    user = await repo.get_user()
    if not user or not user.get("profile_complete"):
        raise HTTPException(
            status_code=400,
            detail="Profile not complete. Please complete your profile first.",
        )


@app.post("/api/chat/message", response_model=ChatResponse)
async def chat_message(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    _: None = Depends(chat_message_rate_limit),
):
    trace_id_var.set(new_trace_id())
    repo = UserScopedRepo(get_db(), user_id)
    await _authorize_chat_request(payload, user_id, repo)

    # Translate-at-the-edges (backend/speech/multilingual.py): the pipeline
    # only ever sees English; the reply goes back in the message's language.
    settings = get_settings()
    inbound = await multilingual.inbound(settings, payload.message, payload.language)

    result = await run_chat_pipeline(
        user_id=user_id,
        session_id=payload.session_id,
        user_message=inbound.english_text,
    )
    return await _finalize_chat_response(payload, repo, inbound, result)


@app.post("/api/chat/message/stream")
async def chat_message_stream(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    _: None = Depends(chat_message_rate_limit),
):
    """Server-Sent Events version of /api/chat/message. Emits a `progress`
    event as each pipeline stage completes (real stage completions, not a
    fake timer), then one `done` event carrying the exact same JSON body
    /api/chat/message returns. See stream_chat_pipeline()'s docstring for why
    this streams stage progress rather than raw model tokens: the output
    guardrail must see a complete response before it can pass or reject it,
    so token-level streaming would risk showing the user text that's about
    to be retracted."""
    trace_id_var.set(new_trace_id())
    repo = UserScopedRepo(get_db(), user_id)
    await _authorize_chat_request(payload, user_id, repo)

    settings = get_settings()
    inbound = await multilingual.inbound(settings, payload.message, payload.language)

    async def event_source():
        final_state: dict[str, Any] = {}
        try:
            async for event in stream_chat_pipeline(
                user_id=user_id,
                session_id=payload.session_id,
                user_message=inbound.english_text,
            ):
                if event["type"] == "progress":
                    yield f"event: progress\ndata: {json.dumps({'label': event['label']})}\n\n"
                else:
                    final_state = event["state"]

            chat_response = await _finalize_chat_response(payload, repo, inbound, final_state)
            yield f"event: done\ndata: {chat_response.model_dump_json()}\n\n"
        except Exception:
            logger.exception("Streaming chat pipeline failed")
            error_payload = json.dumps({"detail": "Something went wrong generating a response. Please try again."})
            yield f"event: error\ndata: {error_payload}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── /api/speech ───────────────────────────────────────────────────────────────

@app.get("/api/speech/token", response_model=SpeechTokenResponse)
async def get_speech_token(user_id: str = Depends(get_current_user_id)):
    """Short-lived Azure Speech token for browser-side recognition. The
    subscription key never leaves the server; the browser gets a 10-minute
    token and the candidate languages to auto-detect between -- the user's
    own "languages I speak" list, or the server default if they never set one."""
    settings = get_settings()
    if not speech_token.is_configured(settings):
        raise HTTPException(status_code=503, detail="Voice input is not configured on this server.")
    try:
        issued = await speech_token.issue_token(settings)
    except Exception as exc:
        logger.exception("Speech token request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not obtain a speech token from Azure.") from exc
    user = await UserScopedRepo(get_db(), user_id).get_user()
    return SpeechTokenResponse(
        token=issued.token,
        region=issued.region,
        expires_in_seconds=issued.expires_in_seconds,
        languages=speech_locales.languages_for_user(settings, user),
    )


@app.get("/api/speech/languages", response_model=SpokenLanguagesResponse)
async def list_spoken_languages(_: str = Depends(get_current_user_id)):
    """The locales a user may pick for "languages I speak" on their profile."""
    return SpokenLanguagesResponse(
        supported=[SpokenLocale(code=c, label=l) for c, l in speech_locales.SUPPORTED_SPOKEN_LOCALES.items()],
        default=speech_locales.default_spoken_languages(get_settings()),
        max_selectable=speech_locales.MAX_SPOKEN_LANGUAGES,
    )


@app.get("/api/chat/sessions")
async def list_sessions(user_id: str = Depends(get_current_user_id)):
    sessions = await UserScopedRepo(get_db(), user_id).get_user_sessions()
    return {"sessions": sessions}


@app.delete("/api/chat/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = Depends(get_current_user_id)):
    deleted = await UserScopedRepo(get_db(), user_id).delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@app.get("/api/chat/history", response_model=HistoryResponse)
async def chat_history(
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
):
    messages_raw = await UserScopedRepo(get_db(), user_id).get_session_messages(session_id, limit=50)
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
    user = await UserScopedRepo(get_db(), user_id).get_user()
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
    plans = await UserScopedRepo(get_db(), user_id).get_accepted_plans()
    return {"plans": plans}


def _pdf_response(pdf_bytes: bytes, user_name: str) -> Response:
    slug = "".join(ch for ch in user_name.lower() if ch.isalnum()) or "user"
    filename = f"nutribot-meal-plan-{slug}-{datetime.utcnow().date().isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _render_plan_for_user(user_id: str, plan_data: dict) -> Response:
    # Validate the shape before rendering so a malformed plan is a clean 422,
    # not a reportlab traceback.
    try:
        plan = WeeklyMealPlan(**plan_data).model_dump()
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid plan: {exc.errors()[0].get('msg', 'shape mismatch')}") from exc
    if not plan["days"]:
        raise HTTPException(status_code=422, detail="Invalid plan: it has no days.")

    user = await UserScopedRepo(get_db(), user_id).get_user() or {}
    user_name = (user.get("full_name") or "").split()[0] or "there"
    pdf_bytes = render_meal_plan_pdf(
        plan,
        user_name=user_name,
        bot_name=user.get("bot_name", "Nova"),
        profile=user,
    )
    return _pdf_response(pdf_bytes, user_name)


@app.post("/api/plans/pdf")
async def download_plan_pdf(payload: PlanPdfRequest, user_id: str = Depends(get_current_user_id)):
    """Render a plan (proposed or accepted -- whatever the client holds) as a
    downloadable PDF. Numbers are taken verbatim from the plan; the plan
    itself was computed by plan_builder, so the document is correct by
    construction."""
    return await _render_plan_for_user(user_id, payload.plan_data)


@app.get("/api/plans/{plan_id}/pdf")
async def download_saved_plan_pdf(plan_id: str, user_id: str = Depends(get_current_user_id)):
    """The same document for a previously accepted plan, by its plan_id."""
    plans = await UserScopedRepo(get_db(), user_id).get_accepted_plans()
    match = next((p for p in plans if p.get("plan_id") == plan_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return await _render_plan_for_user(user_id, match.get("plan_full") or {})


# ── /api/consent ──────────────────────────────────────────────────────────────

@app.post("/api/consent/grant", response_model=ConsentStatusResponse)
async def grant_consent(user_id: str = Depends(get_current_user_id)):
    repo = UserScopedRepo(get_db(), user_id)
    await repo.record_consent(MEDICAL_CONSENT_TYPE, "granted")
    status_doc = await repo.get_consent_status(MEDICAL_CONSENT_TYPE)
    return ConsentStatusResponse(consent_type=MEDICAL_CONSENT_TYPE, **status_doc)


@app.post("/api/consent/revoke", response_model=ConsentStatusResponse)
async def revoke_consent(user_id: str = Depends(get_current_user_id)):
    repo = UserScopedRepo(get_db(), user_id)
    await repo.record_consent(MEDICAL_CONSENT_TYPE, "revoked")
    status_doc = await repo.get_consent_status(MEDICAL_CONSENT_TYPE)
    return ConsentStatusResponse(consent_type=MEDICAL_CONSENT_TYPE, **status_doc)


@app.get("/api/consent/status", response_model=ConsentStatusResponse)
async def consent_status(user_id: str = Depends(get_current_user_id)):
    repo = UserScopedRepo(get_db(), user_id)
    status_doc = await repo.get_consent_status(MEDICAL_CONSENT_TYPE)
    return ConsentStatusResponse(consent_type=MEDICAL_CONSENT_TYPE, **status_doc)


# ── /api/documents ────────────────────────────────────────────────────────────

@app.post("/api/documents/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    repo = UserScopedRepo(get_db(), user_id)

    # Document upload is unconditionally medical data (unlike profile writes,
    # which only gate when medical_conditions is non-empty) -- check directly
    # rather than via _require_medical_consent, which short-circuits on falsy input.
    status_doc = await repo.get_consent_status(MEDICAL_CONSENT_TYPE)
    if not status_doc["granted"]:
        raise HTTPException(
            status_code=403,
            detail="Medical data processing consent required before uploading a document. "
                   "Grant it via POST /api/consent/grant first.",
        )

    content = await file.read()
    try:
        validate_upload(file.filename or "", file.content_type or "", len(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document_id = str(ObjectId())
    blob_path = await blob_client.upload(user_id, document_id, file.filename, content, file.content_type)
    await repo.create_document_record(
        document_id=document_id,
        filename=file.filename,
        content_type=file.content_type,
        document_type=document_type_for(file.content_type),
        blob_path=blob_path,
        size_bytes=len(content),
    )
    await repo.log_access("medical_document", "write", trace_id_var.get())

    await repo.update_document_status(document_id, "processing")
    try:
        raw_text = await doc_intelligence.extract_text(settings, content, file.content_type)
        facts_count = await process_document(repo, document_id, raw_text)
        await repo.update_document_status(document_id, "processed", facts_extracted=facts_count)
    except Exception as exc:
        logger.exception("Document processing failed")
        await repo.update_document_status(document_id, "failed", error_message=str(exc))

    doc = await repo.get_document(document_id)
    return DocumentUploadResponse(id=document_id, status=doc["status"], facts_extracted=doc["facts_extracted"])


@app.get("/api/documents", response_model=list[MedicalDocumentSummary])
async def list_documents(user_id: str = Depends(get_current_user_id)):
    repo = UserScopedRepo(get_db(), user_id)
    await repo.log_access("medical_document", "read", trace_id_var.get())
    docs = await repo.list_documents()
    return [MedicalDocumentSummary(id=str(d["_id"]), **{k: v for k, v in d.items() if k in MedicalDocumentSummary.model_fields}) for d in docs]


@app.get("/api/documents/{document_id}", response_model=MedicalDocumentSummary)
async def get_document(document_id: str, user_id: str = Depends(get_current_user_id)):
    repo = UserScopedRepo(get_db(), user_id)
    doc = await repo.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await repo.log_access("medical_document", "read", trace_id_var.get())
    return MedicalDocumentSummary(id=str(doc["_id"]), **{k: v for k, v in doc.items() if k in MedicalDocumentSummary.model_fields})


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str, user_id: str = Depends(get_current_user_id)):
    repo = UserScopedRepo(get_db(), user_id)
    doc = await repo.delete_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await blob_client.delete(doc["blob_path"])
    await repo.log_access("medical_document", "delete", trace_id_var.get())
    return {"status": "deleted"}


@app.post("/api/documents/delete-batch", response_model=DocumentDeleteResponse)
async def delete_documents_batch(
    payload: DocumentBatchDeleteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Lets the user pick specific uploaded files (e.g. from a "clear medical
    history" screen listing filenames) and delete just those -- the file and
    its metadata are removed, but any facts already extracted into memories
    stay, so the assistant doesn't lose context the user already shared."""
    repo = UserScopedRepo(get_db(), user_id)
    deleted_docs = await repo.delete_documents(payload.document_ids)
    for doc in deleted_docs:
        await blob_client.delete(doc["blob_path"])
    if deleted_docs:
        await repo.log_access("medical_document", "delete", trace_id_var.get())
    deleted_ids = {str(d["_id"]) for d in deleted_docs}
    not_found = [did for did in payload.document_ids if did not in deleted_ids]
    return DocumentDeleteResponse(deleted_count=len(deleted_docs), not_found_ids=not_found)


@app.delete("/api/documents", response_model=DocumentDeleteResponse)
async def clear_all_documents(user_id: str = Depends(get_current_user_id)):
    """"Clear all" -- every uploaded file and its metadata, for this user only.
    Extracted memory facts are untouched, same as the single/batch deletes."""
    repo = UserScopedRepo(get_db(), user_id)
    deleted_docs = await repo.delete_documents(None)
    await blob_client.delete_prefix(user_id)
    if deleted_docs:
        await repo.log_access("medical_document", "delete", trace_id_var.get())
    return DocumentDeleteResponse(deleted_count=len(deleted_docs))


# ── /api/user (export / delete) ─────────────────────────────────────────────────

@app.get("/api/user/export")
async def export_user_data(user_id: str = Depends(get_current_user_id)):
    return await UserScopedRepo(get_db(), user_id).export_all()


@app.delete("/api/user/account")
async def delete_user_account(user_id: str = Depends(get_current_user_id)):
    # Blobs before Mongo: delete_prefix() is keyed only on user_id (doesn't
    # need to enumerate blob_paths from Mongo first), so it's retryable/
    # idempotent even if this fails partway -- deleting Mongo first would risk
    # orphaning blobs with no record left to retry cleanup against.
    await blob_client.delete_prefix(user_id)
    await UserScopedRepo(get_db(), user_id).delete_all()
    return {"status": "deleted"}
