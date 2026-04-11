"""MongoDB connection and CRUD helpers using Motor (async)."""
from datetime import datetime
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from backend.config import get_settings

_client: Optional[AsyncIOMotorClient] = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=5000,  # fail fast if unreachable
        )
    return _client


def get_db() -> AsyncIOMotorDatabase:
    settings = get_settings()
    return get_client()[settings.mongodb_db_name]


async def close_client() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    doc = await get_db().users.find_one({"email": email})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    from bson import ObjectId
    doc = await get_db().users.find_one({"_id": ObjectId(user_id)})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def get_user_by_google_id(google_id: str) -> Optional[dict[str, Any]]:
    doc = await get_db().users.find_one({"google_id": google_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def create_user(data: dict[str, Any]) -> str:
    """Insert a new user document. Returns the new user's string ID."""
    result = await get_db().users.insert_one(data)
    return str(result.inserted_id)


async def update_user(user_id: str, updates: dict[str, Any]) -> None:
    from bson import ObjectId
    updates["updated_at"] = datetime.utcnow()
    await get_db().users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": updates},
    )


# ── Chat Sessions ─────────────────────────────────────────────────────────────

async def get_or_create_session(user_id: str, session_id: str) -> dict[str, Any]:
    doc = await get_db().chat_sessions.find_one(
        {"user_id": user_id, "session_id": session_id}
    )
    if not doc:
        doc = {
            "user_id": user_id,
            "session_id": session_id,
            "started_at": datetime.utcnow(),
            "messages": [],
        }
        await get_db().chat_sessions.insert_one(doc)
    return doc


async def append_messages(
    user_id: str,
    session_id: str,
    messages: list[dict[str, Any]],
) -> None:
    await get_db().chat_sessions.update_one(
        {"user_id": user_id, "session_id": session_id},
        {"$push": {"messages": {"$each": messages}}},
        upsert=True,
    )


async def get_session_messages(
    user_id: str,
    session_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    doc = await get_db().chat_sessions.find_one(
        {"user_id": user_id, "session_id": session_id}
    )
    if not doc:
        return []
    messages = doc.get("messages", [])
    return messages[-limit:]


async def get_chat_history(user_id: str, n: int = 20) -> list[dict[str, Any]]:
    """Return last n messages across all sessions for a user (most recent session first)."""
    cursor = get_db().chat_sessions.find(
        {"user_id": user_id},
        sort=[("started_at", -1)],
        limit=1,
    )
    docs = await cursor.to_list(length=1)
    if not docs:
        return []
    messages = docs[0].get("messages", [])
    return messages[-n:]


# ── Accepted Plans ────────────────────────────────────────────────────────────

async def get_accepted_plans(user_id: str) -> list[dict[str, Any]]:
    doc = await get_db().accepted_plans.find_one({"user_id": user_id})
    if not doc:
        return []
    return doc.get("accepted_plans", [])


async def save_accepted_plan(user_id: str, plan: dict[str, Any]) -> None:
    """Upsert plan into accepted_plans, keeping only the last 2."""
    existing = await get_db().accepted_plans.find_one({"user_id": user_id})
    if existing:
        plans: list = existing.get("accepted_plans", [])
        plans.append(plan)
        # Keep only last 2
        plans = plans[-2:]
        await get_db().accepted_plans.update_one(
            {"user_id": user_id},
            {"$set": {"accepted_plans": plans}},
        )
    else:
        await get_db().accepted_plans.insert_one(
            {"user_id": user_id, "accepted_plans": [plan]}
        )
