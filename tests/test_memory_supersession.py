"""Tests for UserScopedRepo's long-term memory supersession logic and
episodic events (v2 roadmap Phase 3), using mongomock-motor (in-memory,
zero network/secrets, consistent with the rest of the CI suite).
"""
import pytest
import pytest_asyncio
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from backend.db.mongo import UserScopedRepo


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    return client["test_db"]


@pytest_asyncio.fixture
async def two_users(db):
    uid_a, uid_b = ObjectId(), ObjectId()
    await db.users.insert_one({"_id": uid_a, "email": "a@x.com", "full_name": "A"})
    await db.users.insert_one({"_id": uid_b, "email": "b@x.com", "full_name": "B"})
    return UserScopedRepo(db, str(uid_a)), UserScopedRepo(db, str(uid_b))


# ── Supersession: goal_context auto-supersedes ───────────────────────────────

@pytest.mark.asyncio
async def test_goal_context_fact_supersedes_prior_one(two_users):
    repo_a, _ = two_users
    await repo_a.add_memory_fact("Currently focused on fat loss", "goal_context")
    await repo_a.add_memory_fact("Currently focused on muscle gain", "goal_context")

    active = await repo_a.get_active_memories(limit=10)
    assert len(active) == 1
    assert active[0]["fact"] == "Currently focused on muscle gain"


@pytest.mark.asyncio
async def test_superseded_fact_is_marked_not_deleted(db, two_users):
    repo_a, _ = two_users
    await repo_a.add_memory_fact("Old goal", "goal_context")
    await repo_a.add_memory_fact("New goal", "goal_context")

    all_facts = await db.memories.find({"user_id": repo_a.user_id}).to_list(length=None)
    assert len(all_facts) == 2  # both retained
    statuses = {f["fact"]: f["status"] for f in all_facts}
    assert statuses["Old goal"] == "superseded"
    assert statuses["New goal"] == "active"


# ── No supersession: preference/dislike facts coexist ────────────────────────

@pytest.mark.asyncio
async def test_preference_facts_coexist(two_users):
    repo_a, _ = two_users
    await repo_a.add_memory_fact("Dislikes oats", "dislike")
    await repo_a.add_memory_fact("Dislikes broccoli", "dislike")

    active = await repo_a.get_active_memories(limit=10)
    assert len(active) == 2


@pytest.mark.asyncio
async def test_get_active_memories_respects_limit(two_users):
    repo_a, _ = two_users
    for i in range(5):
        await repo_a.add_memory_fact(f"Fact {i}", "preference")

    active = await repo_a.get_active_memories(limit=3)
    assert len(active) == 3


# ── Cross-user isolation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_memories_are_isolated_per_user(two_users):
    repo_a, repo_b = two_users
    await repo_b.add_memory_fact("B's fact", "preference")

    assert await repo_a.get_active_memories() == []
    assert len(await repo_b.get_active_memories()) == 1


@pytest.mark.asyncio
async def test_episodic_events_are_isolated_per_user(two_users):
    repo_a, repo_b = two_users
    await repo_b.add_episodic_event("plan_accepted", {"plan_id": "p1"})

    assert await repo_a.get_recent_events() == []
    events_b = await repo_b.get_recent_events()
    assert len(events_b) == 1
    assert events_b[0]["event_type"] == "plan_accepted"


@pytest.mark.asyncio
async def test_goal_context_supersession_is_scoped_per_user(two_users):
    """A auto-superseding B's goal_context fact would be a cross-user leak."""
    repo_a, repo_b = two_users
    await repo_b.add_memory_fact("B's goal", "goal_context")
    await repo_a.add_memory_fact("A's goal", "goal_context")

    active_b = await repo_b.get_active_memories()
    assert len(active_b) == 1
    assert active_b[0]["status"] == "active"
    assert active_b[0]["fact"] == "B's goal"


# ── Export / delete include the new collections ──────────────────────────────

@pytest.mark.asyncio
async def test_export_includes_memories_and_events(two_users):
    repo_a, _ = two_users
    await repo_a.add_memory_fact("A fact", "preference")
    await repo_a.add_episodic_event("plan_accepted", {"plan_id": "p1"})

    export = await repo_a.export_all()
    assert len(export["memories"]) == 1
    assert len(export["episodic_events"]) == 1


@pytest.mark.asyncio
async def test_delete_removes_memories_and_events(two_users):
    repo_a, _ = two_users
    await repo_a.add_memory_fact("A fact", "preference")
    await repo_a.add_episodic_event("plan_accepted", {"plan_id": "p1"})

    await repo_a.delete_all()

    assert await repo_a.get_active_memories() == []
    assert await repo_a.get_recent_events() == []
