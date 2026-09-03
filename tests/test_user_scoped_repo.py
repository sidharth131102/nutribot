"""Tests for backend/db/mongo.py's UserScopedRepo.

Uses mongomock-motor (an in-memory, Motor-API-compatible fake) so these run
real query execution with zero network/secrets -- consistent with the rest
of the CI suite. This is the "a cross-user read test fails to return data"
test the v2 roadmap Phase 2 DoD asks for.
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


# ── Cross-user isolation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_sessions_are_isolated_per_user(two_users):
    repo_a, repo_b = two_users
    await repo_b.append_messages("s1", [{"role": "user", "content": "hello from B"}])

    assert await repo_a.get_user_sessions() == []
    assert len(await repo_b.get_user_sessions()) == 1


@pytest.mark.asyncio
async def test_accepted_plans_are_isolated_per_user(two_users):
    repo_a, repo_b = two_users
    await repo_b.save_accepted_plan({"plan_id": "p1", "plan_summary": "B's plan"})

    assert await repo_a.get_accepted_plans() == []
    plans_b = await repo_b.get_accepted_plans()
    assert len(plans_b) == 1
    assert plans_b[0]["plan_id"] == "p1"


@pytest.mark.asyncio
async def test_consent_is_isolated_per_user(two_users):
    repo_a, repo_b = two_users
    await repo_b.record_consent("medical_data_processing", "granted")

    status_a = await repo_a.get_consent_status("medical_data_processing")
    status_b = await repo_b.get_consent_status("medical_data_processing")
    assert status_a["granted"] is False
    assert status_b["granted"] is True


# ── Consent grant/revoke round-trip ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_consent_defaults_to_not_granted(two_users):
    repo_a, _ = two_users
    status = await repo_a.get_consent_status("medical_data_processing")
    assert status == {"granted": False, "last_updated": None}


@pytest.mark.asyncio
async def test_consent_grant_then_revoke(two_users):
    repo_a, _ = two_users
    await repo_a.record_consent("medical_data_processing", "granted")
    assert (await repo_a.get_consent_status("medical_data_processing"))["granted"] is True

    await repo_a.record_consent("medical_data_processing", "revoked")
    assert (await repo_a.get_consent_status("medical_data_processing"))["granted"] is False


@pytest.mark.asyncio
async def test_consent_history_is_preserved_not_overwritten(two_users, db):
    repo_a, _ = two_users
    await repo_a.record_consent("medical_data_processing", "granted")
    await repo_a.record_consent("medical_data_processing", "revoked")
    await repo_a.record_consent("medical_data_processing", "granted")

    events = await db.consents.find({"user_id": repo_a.user_id}).to_list(length=None)
    assert len(events) == 3


# ── Export / delete ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_includes_everything_for_this_user(two_users):
    repo_a, _ = two_users
    await repo_a.append_messages("s1", [{"role": "user", "content": "hi"}])
    await repo_a.save_accepted_plan({"plan_id": "p1"})
    await repo_a.record_consent("medical_data_processing", "granted")

    export = await repo_a.export_all()
    assert export["user"]["email"] == "a@x.com"
    assert len(export["chat_sessions"]) == 1
    assert export["accepted_plans"]["accepted_plans"][0]["plan_id"] == "p1"
    assert len(export["consents"]) == 1


@pytest.mark.asyncio
async def test_export_never_includes_password_hash(db, two_users):
    repo_a, _ = two_users
    await db.users.update_one(
        {"_id": ObjectId(repo_a.user_id)}, {"$set": {"password_hash": "should-not-leak"}}
    )
    export = await repo_a.export_all()
    assert "password_hash" not in export["user"]


@pytest.mark.asyncio
async def test_delete_removes_everything_and_export_returns_nothing_after(two_users):
    repo_a, repo_b = two_users
    await repo_a.append_messages("s1", [{"role": "user", "content": "hi"}])
    await repo_a.save_accepted_plan({"plan_id": "p1"})
    await repo_a.record_consent("medical_data_processing", "granted")

    await repo_a.delete_all()

    assert await repo_a.get_user() is None
    assert await repo_a.get_user_sessions() == []
    assert await repo_a.get_accepted_plans() == []
    assert (await repo_a.get_consent_status("medical_data_processing"))["granted"] is False

    # User B's data must be untouched by A's delete
    await repo_b.append_messages("s1", [{"role": "user", "content": "still here"}])
    assert len(await repo_b.get_user_sessions()) == 1


# ── Access audit ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_access_is_scoped_per_user(two_users, db):
    repo_a, repo_b = two_users
    await repo_a.log_access("medical_conditions_allergies", "read", trace_id="t1")

    audit_a = await db.access_audit.find({"user_id": repo_a.user_id}).to_list(length=None)
    audit_b = await db.access_audit.find({"user_id": repo_b.user_id}).to_list(length=None)
    assert len(audit_a) == 1
    assert audit_a[0]["data_type"] == "medical_conditions_allergies"
    assert audit_a[0]["trace_id"] == "t1"
    assert len(audit_b) == 0
