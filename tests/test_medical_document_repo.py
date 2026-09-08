"""Tests for backend/db/mongo.py's medical-document UserScopedRepo methods
(v2 roadmap Phase 4), using mongomock-motor (in-memory, zero network/secrets,
consistent with the rest of the CI suite).
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


async def _create(repo, filename="report.pdf"):
    document_id = str(ObjectId())
    await repo.create_document_record(
        document_id=document_id,
        filename=filename,
        content_type="application/pdf",
        document_type="pdf",
        blob_path=f"{repo.user_id}/{document_id}/{filename}",
        size_bytes=1024,
    )
    return document_id


# ── Create / list / get round-trip ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_then_list_round_trip(two_users):
    repo_a, _ = two_users
    document_id = await _create(repo_a)

    docs = await repo_a.list_documents()
    assert len(docs) == 1
    assert str(docs[0]["_id"]) == document_id
    assert docs[0]["status"] == "uploaded"


@pytest.mark.asyncio
async def test_list_orders_newest_first(two_users):
    repo_a, _ = two_users
    first = await _create(repo_a, "old.pdf")
    second = await _create(repo_a, "new.pdf")

    docs = await repo_a.list_documents()
    assert [str(d["_id"]) for d in docs] == [second, first]


@pytest.mark.asyncio
async def test_get_document_returns_the_record(two_users):
    repo_a, _ = two_users
    document_id = await _create(repo_a)

    doc = await repo_a.get_document(document_id)
    assert doc is not None
    assert doc["filename"] == "report.pdf"


# ── Status transitions ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_transitions_to_processed_sets_facts_and_processed_at(two_users):
    repo_a, _ = two_users
    document_id = await _create(repo_a)

    await repo_a.update_document_status(document_id, "processing")
    doc = await repo_a.get_document(document_id)
    assert doc["status"] == "processing"
    assert doc["processed_at"] is None

    await repo_a.update_document_status(document_id, "processed", facts_extracted=3)
    doc = await repo_a.get_document(document_id)
    assert doc["status"] == "processed"
    assert doc["facts_extracted"] == 3
    assert doc["processed_at"] is not None


@pytest.mark.asyncio
async def test_status_transitions_to_failed_sets_error_message(two_users):
    repo_a, _ = two_users
    document_id = await _create(repo_a)

    await repo_a.update_document_status(document_id, "failed", error_message="OCR timed out")
    doc = await repo_a.get_document(document_id)
    assert doc["status"] == "failed"
    assert doc["error_message"] == "OCR timed out"
    assert doc["processed_at"] is not None


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_document_returns_deleted_record_and_removes_it(two_users):
    repo_a, _ = two_users
    document_id = await _create(repo_a)

    deleted = await repo_a.delete_document(document_id)
    assert deleted is not None
    assert str(deleted["_id"]) == document_id

    assert await repo_a.get_document(document_id) is None
    assert await repo_a.list_documents() == []


@pytest.mark.asyncio
async def test_delete_nonexistent_document_returns_none(two_users):
    repo_a, _ = two_users
    assert await repo_a.delete_document(str(ObjectId())) is None


# ── Cross-user isolation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_documents_are_isolated_per_user(two_users):
    repo_a, repo_b = two_users
    await _create(repo_b)

    assert await repo_a.list_documents() == []
    assert len(await repo_b.list_documents()) == 1


@pytest.mark.asyncio
async def test_get_document_does_not_leak_across_users(two_users):
    repo_a, repo_b = two_users
    document_id = await _create(repo_b)

    assert await repo_a.get_document(document_id) is None
    assert await repo_b.get_document(document_id) is not None


@pytest.mark.asyncio
async def test_delete_document_does_not_leak_across_users(two_users):
    repo_a, repo_b = two_users
    document_id = await _create(repo_b)

    assert await repo_a.delete_document(document_id) is None
    # B's document is untouched by A's failed attempt
    assert await repo_b.get_document(document_id) is not None


# ── Export / delete ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_includes_medical_documents(two_users):
    repo_a, _ = two_users
    await _create(repo_a)

    export = await repo_a.export_all()
    assert len(export["medical_documents"]) == 1


@pytest.mark.asyncio
async def test_delete_all_removes_medical_documents(two_users):
    repo_a, _ = two_users
    await _create(repo_a)

    await repo_a.delete_all()

    assert await repo_a.list_documents() == []
