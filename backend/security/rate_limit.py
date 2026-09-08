"""Mongo-backed rate limiting (Phase 6).

No Redis or any other shared-state store exists anywhere in this codebase --
an in-memory counter would reset per Vercel serverless instance/cold start
and wouldn't actually limit anything in production, so counters live in
MongoDB (the one real shared store available), TTL-cleaned the same way
backend/db/mongo.py already does for access_audit.
"""
import time
from datetime import datetime, timedelta
from typing import Callable

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel
from pymongo import ReturnDocument

from backend.auth.jwt_handler import get_current_user_id
from backend.db.mongo import get_db


class RateLimitResult(BaseModel):
    allowed: bool
    retry_after_seconds: int


def _get_client_ip(request: Request) -> str:
    """Vercel sits in front of this app -- request.client.host would be the
    proxy's IP, not the real client's, so X-Forwarded-For (set by Vercel's
    edge) is checked first."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_rate_limit(scope: str, key: str, limit: int, window_seconds: int) -> RateLimitResult:
    """Fixed-window counter: one document per (scope, key, window), atomic
    upsert-increment so concurrent requests can't race past the limit."""
    now = time.time()
    window_bucket = int(now // window_seconds)
    window_end = (window_bucket + 1) * window_seconds
    retry_after = max(1, int(window_end - now))
    doc_id = f"{scope}:{key}:{window_bucket}"

    doc = await get_db().rate_limit_counters.find_one_and_update(
        {"_id": doc_id},
        {
            "$inc": {"count": 1},
            "$setOnInsert": {
                "scope": scope,
                "key": key,
                # Double the window as a buffer against mid-window TTL expiry
                "expires_at": datetime.utcnow() + timedelta(seconds=window_seconds * 2),
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return RateLimitResult(allowed=doc["count"] <= limit, retry_after_seconds=retry_after)


def _raise_if_blocked(result: RateLimitResult) -> None:
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {result.retry_after_seconds} seconds.",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


def rate_limit_by_ip(scope: str, limit: int, window_seconds: int) -> Callable:
    async def _dep(request: Request) -> None:
        _raise_if_blocked(await check_rate_limit(scope, _get_client_ip(request), limit, window_seconds))
    return _dep


def rate_limit_by_user(scope: str, limit: int, window_seconds: int) -> Callable:
    async def _dep(user_id: str = Depends(get_current_user_id)) -> None:
        _raise_if_blocked(await check_rate_limit(scope, user_id, limit, window_seconds))
    return _dep


# Ready-made dependencies for main.py -- thresholds are hardcoded constants
# here, not Settings fields, matching this codebase's existing convention
# for CALORIE_TOLERANCE/AUDIT_RETENTION_DAYS. Login counts ALL attempts (not
# just failures) -- counting only failures creates a success/failure timing
# side-channel and is unnecessary complexity for the standard mitigation.
register_rate_limit = rate_limit_by_ip("register", limit=5, window_seconds=3600)
login_rate_limit = rate_limit_by_ip("login", limit=10, window_seconds=900)
chat_message_rate_limit = rate_limit_by_user("chat_message", limit=20, window_seconds=300)
