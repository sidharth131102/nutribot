"""MongoDB connection, indexes, and the user-scoped data-access layer (Motor/async).

Per the v2 roadmap Phase 2: every read/write for an authenticated user goes
through UserScopedRepo, which is constructed with that user's id and injects
it into every query automatically -- it's structurally impossible for a
UserScopedRepo method to issue an unfiltered or wrong-user query, unlike a
free function that merely takes a user_id argument by convention.

create_user / get_user_by_email / get_user_by_google_id stay as free
functions: they run before there's an authenticated user_id (registration,
login, OAuth callback), so they can't be user-scoped by construction.
"""
from datetime import datetime
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from backend.config import get_settings

_client: Optional[AsyncIOMotorClient] = None

AUDIT_RETENTION_DAYS = 90


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
            socketTimeoutMS=10000,
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


async def ensure_indexes() -> None:
    """Create/confirm indexes. Idempotent -- safe to call on every startup."""
    db = get_db()
    await db.users.create_index("email", unique=True)
    # Partial, not sparse: registration explicitly sets google_id=None for
    # email-registered users (present-but-null, not absent), and a sparse
    # index only excludes documents missing the field entirely -- it still
    # treats every present-but-null value as a duplicate under `unique`.
    await db.users.create_index(
        "google_id",
        unique=True,
        partialFilterExpression={"google_id": {"$type": "string"}},
    )
    await db.chat_sessions.create_index([("user_id", 1), ("session_id", 1)])
    await db.chat_sessions.create_index("user_id")
    await db.accepted_plans.create_index("user_id")
    await db.consents.create_index("user_id")
    await db.access_audit.create_index("user_id")
    await db.access_audit.create_index("timestamp", expireAfterSeconds=AUDIT_RETENTION_DAYS * 86400)
    await db.memories.create_index("user_id")
    await db.episodic_events.create_index("user_id")
    await db.medical_documents.create_index("user_id")
    # expireAfterSeconds=0 -- expires exactly at the stored expires_at
    # timestamp (vs. access_audit's fixed-offset-from-insert-time TTL above),
    # needed because rate_limit_counters shares one collection across scopes
    # with different window lengths.
    await db.rate_limit_counters.create_index("expires_at", expireAfterSeconds=0)


# ── Pre-auth free functions (no user_id to scope by yet) ───────────────────────

async def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    doc = await get_db().users.find_one({"email": email})
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


class UserScopedRepo:
    """All authenticated-user data access goes through here. Every method is
    scoped to `self.user_id` -- there is no method that can read or write
    another user's documents."""

    def __init__(self, db: AsyncIOMotorDatabase, user_id: str):
        self._db = db
        self.user_id = user_id

    # ── User record ──────────────────────────────────────────────────────────

    async def get_user(self) -> Optional[dict[str, Any]]:
        from bson import ObjectId
        doc = await self._db.users.find_one({"_id": ObjectId(self.user_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
        return doc

    async def update_user(self, updates: dict[str, Any]) -> None:
        from bson import ObjectId
        updates = {**updates, "updated_at": datetime.utcnow()}
        await self._db.users.update_one(
            {"_id": ObjectId(self.user_id)},
            {"$set": updates},
        )

    # ── Chat sessions ────────────────────────────────────────────────────────

    async def get_or_create_session(self, session_id: str) -> dict[str, Any]:
        doc = await self._db.chat_sessions.find_one(
            {"user_id": self.user_id, "session_id": session_id}
        )
        if not doc:
            doc = {
                "user_id": self.user_id,
                "session_id": session_id,
                "started_at": datetime.utcnow(),
                "messages": [],
            }
            await self._db.chat_sessions.insert_one(doc)
        return doc

    async def append_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        await self._db.chat_sessions.update_one(
            {"user_id": self.user_id, "session_id": session_id},
            {
                "$push": {"messages": {"$each": messages}},
                "$setOnInsert": {
                    "user_id": self.user_id,
                    "session_id": session_id,
                    "started_at": datetime.utcnow(),
                },
            },
            upsert=True,
        )

    async def get_session_messages(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        doc = await self._db.chat_sessions.find_one(
            {"user_id": self.user_id, "session_id": session_id}
        )
        if not doc:
            return []
        return doc.get("messages", [])[-limit:]

    async def get_user_sessions(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return all sessions for this user, newest first, with a message preview."""
        cursor = self._db.chat_sessions.find(
            {"user_id": self.user_id},
            sort=[("started_at", -1)],
            limit=limit,
        )
        docs = await cursor.to_list(length=limit)
        result = []
        for doc in docs:
            messages = doc.get("messages", [])
            preview = "New conversation"
            for m in messages:
                if m.get("role") == "user":
                    preview = m.get("content", "")[:60]
                    break
            started = doc.get("started_at")
            if hasattr(started, "isoformat"):
                started_str = started.isoformat() + "Z"
            else:
                started_str = doc["_id"].generation_time.isoformat() + "Z"
            result.append({
                "session_id": doc["session_id"],
                "started_at": started_str,
                "preview": preview,
                "message_count": len(messages),
            })
        return result

    async def get_chat_history(self, n: int = 20) -> list[dict[str, Any]]:
        """Last n messages from this user's most recently active session."""
        cursor = self._db.chat_sessions.find(
            {"user_id": self.user_id},
            sort=[("started_at", -1)],
            limit=1,
        )
        docs = await cursor.to_list(length=1)
        if not docs:
            return []
        return docs[0].get("messages", [])[-n:]

    # ── Accepted plans ───────────────────────────────────────────────────────

    async def get_accepted_plans(self) -> list[dict[str, Any]]:
        doc = await self._db.accepted_plans.find_one({"user_id": self.user_id})
        return doc.get("accepted_plans", []) if doc else []

    async def save_accepted_plan(self, plan: dict[str, Any]) -> None:
        """Upsert plan into accepted_plans, keeping only the last 2."""
        existing = await self._db.accepted_plans.find_one({"user_id": self.user_id})
        if existing:
            plans = (existing.get("accepted_plans", []) + [plan])[-2:]
            await self._db.accepted_plans.update_one(
                {"user_id": self.user_id},
                {"$set": {"accepted_plans": plans}},
            )
        else:
            await self._db.accepted_plans.insert_one(
                {"user_id": self.user_id, "accepted_plans": [plan]}
            )

    # ── Consent ──────────────────────────────────────────────────────────────

    async def record_consent(self, consent_type: str, action: str) -> None:
        await self._db.consents.insert_one({
            "user_id": self.user_id,
            "consent_type": consent_type,
            "action": action,
            "timestamp": datetime.utcnow(),
        })

    async def get_consent_status(self, consent_type: str) -> dict[str, Any]:
        """Derived from the latest event for this consent_type -- the log itself
        is append-only, this just reads the current state off the end of it.

        Sorts by _id (not just timestamp) as a monotonic tiebreaker: two events
        recorded within the same millisecond would otherwise sort ambiguously
        on timestamp alone and could return the wrong "current" state."""
        doc = await self._db.consents.find_one(
            {"user_id": self.user_id, "consent_type": consent_type},
            sort=[("timestamp", -1), ("_id", -1)],
        )
        if not doc:
            return {"granted": False, "last_updated": None}
        return {"granted": doc["action"] == "granted", "last_updated": doc["timestamp"]}

    # ── Access audit ─────────────────────────────────────────────────────────

    async def log_access(self, data_type: str, action: str, trace_id: str = "-") -> None:
        await self._db.access_audit.insert_one({
            "user_id": self.user_id,
            "data_type": data_type,
            "action": action,
            "trace_id": trace_id,
            "timestamp": datetime.utcnow(),
        })

    # ── Long-term semantic memory ────────────────────────────────────────────

    # Categories where a new fact represents a change of state rather than an
    # additional, coexisting fact -- adding one here auto-supersedes the prior
    # active fact in that category for this user. Everything else (a user can
    # dislike multiple foods at once, for example) allows multiple active facts.
    _AUTO_SUPERSEDE_CATEGORIES = {"goal_context"}

    async def add_memory_fact(self, fact: str, category: str, source: str = "chat_extraction", confidence: float = 0.7) -> str:
        """Insert a new active fact, auto-superseding the prior one in the same
        category if this category represents current-state-not-a-list."""
        now = datetime.utcnow()
        if category in self._AUTO_SUPERSEDE_CATEGORIES:
            existing = await self._db.memories.find_one({
                "user_id": self.user_id, "category": category, "status": "active",
            })
            if existing:
                await self._supersede(existing["_id"])

        result = await self._db.memories.insert_one({
            "user_id": self.user_id,
            "fact": fact,
            "category": category,
            "source": source,
            "confidence": confidence,
            "created_at": now,
            "last_confirmed": now,
            "status": "active",
            "superseded_by": None,
        })
        return str(result.inserted_id)

    async def _supersede(self, old_id) -> None:
        await self._db.memories.update_one(
            {"_id": old_id},
            {"$set": {"status": "superseded"}},
        )

    async def get_active_memories(self, limit: int = 3) -> list[dict[str, Any]]:
        cursor = self._db.memories.find(
            {"user_id": self.user_id, "status": "active"},
            sort=[("created_at", -1)],
            limit=limit,
        )
        return await cursor.to_list(length=limit)

    # ── Episodic events ──────────────────────────────────────────────────────

    async def add_episodic_event(self, event_type: str, details: dict[str, Any] | None = None) -> None:
        await self._db.episodic_events.insert_one({
            "user_id": self.user_id,
            "event_type": event_type,
            "details": details or {},
            "timestamp": datetime.utcnow(),
        })

    async def get_recent_events(self, limit: int = 2) -> list[dict[str, Any]]:
        cursor = self._db.episodic_events.find(
            {"user_id": self.user_id},
            sort=[("timestamp", -1)],
            limit=limit,
        )
        return await cursor.to_list(length=limit)

    # ── Medical documents ────────────────────────────────────────────────────

    async def create_document_record(
        self, document_id: str, filename: str, content_type: str, document_type: str,
        blob_path: str, size_bytes: int,
    ) -> None:
        """document_id is pre-generated by the caller (ObjectId, stringified) so
        the blob path and the Mongo _id can agree in one pass -- no follow-up
        update needed to backfill blob_path after the blob upload completes."""
        from bson import ObjectId
        await self._db.medical_documents.insert_one({
            "_id": ObjectId(document_id),
            "user_id": self.user_id,
            "filename": filename,
            "content_type": content_type,
            "document_type": document_type,
            "blob_path": blob_path,
            "size_bytes": size_bytes,
            "status": "uploaded",
            "facts_extracted": 0,
            "error_message": None,
            "uploaded_at": datetime.utcnow(),
            "processed_at": None,
        })

    async def update_document_status(
        self, document_id: str, status: str, facts_extracted: int = 0, error_message: str | None = None,
    ) -> None:
        from bson import ObjectId
        updates: dict[str, Any] = {"status": status}
        if status in ("processed", "failed"):
            updates["processed_at"] = datetime.utcnow()
        if status == "processed":
            updates["facts_extracted"] = facts_extracted
        if error_message is not None:
            updates["error_message"] = error_message
        await self._db.medical_documents.update_one(
            {"_id": ObjectId(document_id), "user_id": self.user_id},
            {"$set": updates},
        )

    async def get_document(self, document_id: str) -> Optional[dict[str, Any]]:
        from bson import ObjectId
        try:
            oid = ObjectId(document_id)
        except Exception:
            return None
        return await self._db.medical_documents.find_one({"_id": oid, "user_id": self.user_id})

    async def list_documents(self, limit: int = 20) -> list[dict[str, Any]]:
        # _id as a tiebreaker: two uploads in the same millisecond would
        # otherwise sort ambiguously on uploaded_at alone (same class of bug
        # fixed for get_consent_status above).
        cursor = self._db.medical_documents.find(
            {"user_id": self.user_id},
            sort=[("uploaded_at", -1), ("_id", -1)],
            limit=limit,
        )
        return await cursor.to_list(length=limit)

    async def delete_document(self, document_id: str) -> Optional[dict[str, Any]]:
        """Returns the deleted record (so the caller can delete its blob) or
        None if it doesn't exist or isn't owned by this user."""
        from bson import ObjectId
        try:
            oid = ObjectId(document_id)
        except Exception:
            return None
        return await self._db.medical_documents.find_one_and_delete({"_id": oid, "user_id": self.user_id})

    async def delete_documents(self, document_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Deletes and returns every matching document record, scoped to this
        user. document_ids=None deletes every document this user has -- the
        "clear all" case. Invalid ids are silently skipped rather than raising,
        so a partially-stale client-side list (e.g. one already deleted) doesn't
        fail the whole batch. Returns the deleted records (each with blob_path)
        so the caller can clean up the matching blobs."""
        from bson import ObjectId
        query: dict[str, Any] = {"user_id": self.user_id}
        if document_ids is not None:
            oids = []
            for did in document_ids:
                try:
                    oids.append(ObjectId(did))
                except Exception:
                    continue
            query["_id"] = {"$in": oids}
        docs = await self._db.medical_documents.find(query).to_list(length=None)
        if docs:
            await self._db.medical_documents.delete_many({"_id": {"$in": [d["_id"] for d in docs]}})
        return docs

    # ── Export / delete ──────────────────────────────────────────────────────

    async def export_all(self) -> dict[str, Any]:
        """Everything this app stores about this user, across every collection
        that currently exists."""
        user = await self.get_user()
        if user:
            user.pop("password_hash", None)
        sessions_cursor = self._db.chat_sessions.find({"user_id": self.user_id})
        sessions = await sessions_cursor.to_list(length=None)
        for s in sessions:
            s["_id"] = str(s["_id"])

        plans_doc = await self._db.accepted_plans.find_one({"user_id": self.user_id})
        if plans_doc:
            plans_doc["_id"] = str(plans_doc["_id"])

        consents_cursor = self._db.consents.find({"user_id": self.user_id})
        consents = await consents_cursor.to_list(length=None)
        for c in consents:
            c["_id"] = str(c["_id"])

        memories_cursor = self._db.memories.find({"user_id": self.user_id})
        memories = await memories_cursor.to_list(length=None)
        for m in memories:
            m["_id"] = str(m["_id"])

        events_cursor = self._db.episodic_events.find({"user_id": self.user_id})
        events = await events_cursor.to_list(length=None)
        for e in events:
            e["_id"] = str(e["_id"])

        docs_cursor = self._db.medical_documents.find({"user_id": self.user_id})
        documents = await docs_cursor.to_list(length=None)
        for d in documents:
            d["_id"] = str(d["_id"])

        return {
            "user": user,
            "chat_sessions": sessions,
            "accepted_plans": plans_doc,
            "consents": consents,
            "memories": memories,
            "episodic_events": events,
            "medical_documents": documents,
        }

    async def delete_all(self) -> None:
        """Hard delete -- every document belonging to this user, across every
        collection. Irreversible."""
        from bson import ObjectId
        await self._db.users.delete_one({"_id": ObjectId(self.user_id)})
        await self._db.chat_sessions.delete_many({"user_id": self.user_id})
        await self._db.accepted_plans.delete_many({"user_id": self.user_id})
        await self._db.consents.delete_many({"user_id": self.user_id})
        await self._db.access_audit.delete_many({"user_id": self.user_id})
        await self._db.memories.delete_many({"user_id": self.user_id})
        await self._db.episodic_events.delete_many({"user_id": self.user_id})
        await self._db.medical_documents.delete_many({"user_id": self.user_id})
