"""Tests for backend/security/rate_limit.py -- window-bucket math, atomic
increment (via mongomock-motor), and IP-derivation logic. No real HTTP
requests, no live credentials."""
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from backend.security.rate_limit import _get_client_ip, check_rate_limit


@pytest_asyncio.fixture
async def db(monkeypatch):
    client = AsyncMongoMockClient()
    database = client["test_db"]
    monkeypatch.setattr("backend.security.rate_limit.get_db", lambda: database)
    return database


# ── check_rate_limit ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_allows_requests_under_the_limit(db):
    for _ in range(3):
        result = await check_rate_limit("test_scope", "key1", limit=5, window_seconds=60)
        assert result.allowed is True


@pytest.mark.asyncio
async def test_blocks_requests_over_the_limit(db):
    for _ in range(5):
        await check_rate_limit("test_scope", "key1", limit=5, window_seconds=60)

    result = await check_rate_limit("test_scope", "key1", limit=5, window_seconds=60)
    assert result.allowed is False
    assert result.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_counters_are_scoped_independently(db):
    for _ in range(5):
        await check_rate_limit("scope_a", "key1", limit=5, window_seconds=60)

    # Same key, different scope -- must not share the counter
    result = await check_rate_limit("scope_b", "key1", limit=5, window_seconds=60)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_counters_are_scoped_independently_per_key(db):
    for _ in range(5):
        await check_rate_limit("test_scope", "key1", limit=5, window_seconds=60)

    result = await check_rate_limit("test_scope", "key2", limit=5, window_seconds=60)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_new_window_resets_the_counter(db, monkeypatch):
    fake_now = [1_000_000.0]
    monkeypatch.setattr("backend.security.rate_limit.time.time", lambda: fake_now[0])

    for _ in range(5):
        await check_rate_limit("test_scope", "key1", limit=5, window_seconds=60)
    blocked = await check_rate_limit("test_scope", "key1", limit=5, window_seconds=60)
    assert blocked.allowed is False

    # Jump into the next window bucket
    fake_now[0] += 61
    result = await check_rate_limit("test_scope", "key1", limit=5, window_seconds=60)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_retry_after_is_within_the_window(db):
    result = await check_rate_limit("test_scope", "key1", limit=1, window_seconds=60)
    assert 0 < result.retry_after_seconds <= 60


# ── _get_client_ip ────────────────────────────────────────────────────────────

def _make_request(forwarded_for=None, client_host="10.0.0.1"):
    request = MagicMock()
    request.headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
    request.client = MagicMock(host=client_host) if client_host else None
    return request


def test_get_client_ip_uses_x_forwarded_for_first_entry():
    request = _make_request(forwarded_for="203.0.113.5, 10.0.0.1")
    assert _get_client_ip(request) == "203.0.113.5"


def test_get_client_ip_strips_whitespace():
    request = _make_request(forwarded_for=" 203.0.113.5 ,10.0.0.1")
    assert _get_client_ip(request) == "203.0.113.5"


def test_get_client_ip_falls_back_to_request_client_host():
    request = _make_request(forwarded_for=None, client_host="10.0.0.1")
    assert _get_client_ip(request) == "10.0.0.1"


def test_get_client_ip_falls_back_to_unknown_when_nothing_available():
    request = _make_request(forwarded_for=None, client_host=None)
    assert _get_client_ip(request) == "unknown"
