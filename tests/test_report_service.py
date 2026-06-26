"""
Tests for report_service.py using pytest and FastAPI TestClient.

Run with:  pytest tests/ -v
Or:       python -m pytest tests/ -v

These tests cover the core FastAPI endpoints, middleware behaviour,
and the persistence abstraction layer without requiring a live server
or external API keys.
"""

import json
import os
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

# Set dummy env vars before importing the app so external keys are not required.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy-key")
os.environ.setdefault("GEMINI_API_KEY", "test-dummy-key")
os.environ.setdefault("REPORT_VERIFY_RATE_MAX", "5")
os.environ.setdefault("REPORT_VERIFY_RATE_WINDOW_S", "60")
os.environ.setdefault("REPORT_MAX_REQUEST_BYTES", "5000000")
os.environ.setdefault("REPORT_MAX_DRAFTS", "10")
os.environ.setdefault("REPORT_DRAFT_TTL_HOURS", "1")

# Import persistence layer before the app so we can instantiate fresh backends.
from report_service_persistence import InMemoryDraftStore, InMemoryRateLimiter

# Import the app module and its globals.
import report_service
from report_service import (
    DRAFTS,
    MAX_REQUEST_BODY_BYTES,
    _RATE_BUCKETS,
    _prune_drafts,
    _utcnow,
    app,
)


@pytest.fixture
def client():
    """Yield a TestClient and reset all backend state after each test."""
    # Create fresh in-memory backends for full test isolation.
    fresh_draft_store = InMemoryDraftStore()
    fresh_rate_limiter = InMemoryRateLimiter()

    # Monkeypatch the module-level backends.
    original_draft_store = report_service.draft_store
    original_rate_limiter = report_service.rate_limiter
    report_service.draft_store = fresh_draft_store
    report_service.rate_limiter = fresh_rate_limiter

    # Also clear legacy dicts for backward-compatibility assertions.
    DRAFTS.clear()
    _RATE_BUCKETS.clear()

    with TestClient(app) as c:
        yield c

    # Restore original module-level backends.
    report_service.draft_store = original_draft_store
    report_service.rate_limiter = original_rate_limiter
    DRAFTS.clear()
    _RATE_BUCKETS.clear()


# ────────────────────────────────────────────────────────────
#  /health
# ────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0

    def test_health_includes_backend_status(self, client):
        response = client.get("/health")
        data = response.json()
        assert "draft_store" in data
        assert "rate_limiter" in data
        assert data["draft_store"]["type"] == "memory"
        assert data["rate_limiter"]["type"] == "memory"


# ────────────────────────────────────────────────────────────
#  /report/draft
# ────────────────────────────────────────────────────────────

class TestDraftCreate:
    def test_create_draft_with_valid_payload(self, client):
        payload = {
            "title": "Test Report",
            "payload": {
                "project": {"name": "Demo Project", "location": "Brisbane"},
                "inputs": {"aadt": 5000, "growth_rate_percent": 2.5},
            },
        }
        response = client.post("/report/draft", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "editor_url" in data
        assert data["editor_url"].startswith("/report/editor/")
        draft_id = data["editor_url"].split("/")[-1]
        assert len(draft_id) == 32  # UUID hex

    def test_create_draft_default_title(self, client):
        payload = {"title": "", "payload": {"test": True}}
        response = client.post("/report/draft", json=payload)
        assert response.status_code == 200
        # Title is defaulted to "TIA Report" internally.
        assert response.json()["editor_url"]

    def test_create_draft_title_too_long(self, client):
        payload = {"title": "x" * 200, "payload": {"test": True}}
        response = client.post("/report/draft", json=payload)
        assert response.status_code == 400
        assert "too long" in response.json()["detail"].lower()

    def test_create_draft_payload_too_large(self, client):
        # Build a payload that serialises to > MAX_REQUEST_BODY_BYTES
        big_payload = {"data": "x" * (MAX_REQUEST_BODY_BYTES + 1000)}
        payload = {"title": "Big Report", "payload": big_payload}
        response = client.post("/report/draft", json=payload)
        assert response.status_code == 413
        assert "too large" in response.json()["detail"].lower()

    def test_create_draft_prunes_old_drafts(self, client):
        # Fill drafts to the max (10 per env fixture)
        for i in range(12):
            client.post(
                "/report/draft",
                json={"title": f"Draft {i}", "payload": {"idx": i}},
            )
        # After pruning, count should be at most max_drafts.
        assert len(DRAFTS) <= 10


# ────────────────────────────────────────────────────────────
#  /report/editor/{draft_id}
# ────────────────────────────────────────────────────────────

class TestEditorPage:
    def test_editor_returns_html_for_valid_draft(self, client):
        # Create a draft first
        create_resp = client.post(
            "/report/draft",
            json={
                "title": "Editor Test",
                "payload": {
                    "project": {"name": "P"},
                    "inputs": {},
                    "results": {},
                },
            },
        )
        editor_url = create_resp.json()["editor_url"]
        response = client.get(editor_url)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Traffic Impact Assessment" in response.text

    def test_editor_404_for_missing_draft(self, client):
        response = client.get("/report/editor/00000000000000000000000000000000")
        assert response.status_code == 404

    def test_editor_400_for_invalid_draft_id(self, client):
        response = client.get("/report/editor/not-a-uuid")
        assert response.status_code == 400

    def test_editor_prunes_expired_drafts(self, client):
        # Inject an expired draft via the backend (not the legacy dict)
        old_id = "a" * 32
        report_service.draft_store.set(
            old_id,
            {
                "title": "Old",
                "payload": {},
                "created_at": "2020-01-01T00:00:00Z",
                "created_epoch": 1577836800.0,
            },
        )
        # Accessing editor triggers prune
        response = client.get(f"/report/editor/{old_id}")
        assert response.status_code == 404
        assert old_id not in DRAFTS


# ────────────────────────────────────────────────────────────
#  /verify-formulas
# ────────────────────────────────────────────────────────────

class TestVerifyFormulas:
    def test_verify_no_failures_returns_ok(self, client):
        response = client.post("/verify-formulas", json={"failures": []})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "analysis" in data
        # Rate limit headers should be present
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers

    def test_verify_with_failures_triggers_analysis(self, client):
        # With a dummy ANTHROPIC_API_KEY, the call will fail internally
        # but the endpoint should still return a structured response.
        payload = {
            "failures": [
                {
                    "id": "test-1",
                    "name": "Queue Length Test",
                    "group": "queue",
                    "reference": 100,
                    "actual": 105,
                    "deviation": 5,
                    "error": "Value mismatch",
                }
            ]
        }
        response = client.post("/verify-formulas", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failures_analysed"
        assert data["failure_count"] == 1
        assert "analysis" in data

    def test_verify_rate_limiting(self, client):
        # Hit the endpoint more than the configured max (5 per 60s)
        for _ in range(6):
            response = client.post("/verify-formulas", json={"failures": []})

        # The 6th request should be rate limited
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert "X-RateLimit-Remaining" in response.headers

        # Wait for the window to clear
        time.sleep(1)


# ────────────────────────────────────────────────────────────
#  Security Headers & Middleware
# ────────────────────────────────────────────────────────────

class TestSecurityHeaders:
    def test_security_headers_on_health(self, client):
        response = client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Access-Control-Allow-Private-Network"] == "true"

    def test_csp_on_html_response(self, client):
        # Editor page returns HTML and should have CSP
        create_resp = client.post(
            "/report/draft",
            json={"title": "CSP Test", "payload": {"project": {"name": "P"}}},
        )
        editor_url = create_resp.json()["editor_url"]
        response = client.get(editor_url)
        assert "Content-Security-Policy" in response.headers

    def test_cors_headers_present(self, client):
        response = client.get("/health", headers={"Origin": "http://localhost:5500"})
        assert "access-control-allow-origin" in response.headers


# ────────────────────────────────────────────────────────────
#  Content-Length Middleware
# ────────────────────────────────────────────────────────────

class TestContentLengthMiddleware:
    def test_rejects_oversized_content_length(self, client):
        # Simulate a request with a Content-Length header larger than the limit
        big_size = MAX_REQUEST_BODY_BYTES + 1
        response = client.post(
            "/report/draft",
            headers={"Content-Length": str(big_size)},
            json={"title": "T", "payload": {}},
        )
        assert response.status_code == 413

    def test_rejects_invalid_content_length(self, client):
        response = client.post(
            "/report/draft",
            headers={"Content-Length": "not-a-number"},
            json={"title": "T", "payload": {}},
        )
        assert response.status_code == 400


# ────────────────────────────────────────────────────────────
#  Internal Helpers
# ────────────────────────────────────────────────────────────

class TestInternalHelpers:
    def test_prune_drafts_removes_stale_entries(self):
        # Use the backend directly, then sync via _prune_drafts
        report_service.draft_store.set(
            "old",
            {
                "title": "Old",
                "payload": {},
                "created_at": "2020-01-01T00:00:00Z",
                "created_epoch": 1577836800.0,
            },
        )
        report_service.draft_store.set(
            "new",
            {
                "title": "New",
                "payload": {},
                "created_at": _utcnow().isoformat(),
                "created_epoch": _utcnow().timestamp(),
            },
        )
        _prune_drafts()
        assert "old" not in DRAFTS
        assert "new" in DRAFTS

    def test_utcnow_returns_aware_datetime(self):
        now = _utcnow()
        assert now.tzinfo is not None
        assert now.tzinfo.utcoffset(None) is not None


# ────────────────────────────────────────────────────────────
#  Persistence Layer (DraftStore)
# ────────────────────────────────────────────────────────────

class TestInMemoryDraftStore:
    def test_get_missing_returns_none(self):
        store = InMemoryDraftStore()
        assert store.get("nonexistent") is None

    def test_set_and_get_roundtrip(self):
        store = InMemoryDraftStore()
        store.set("abc", {"title": "Test", "payload": {}})
        assert store.get("abc") == {"title": "Test", "payload": {}}

    def test_delete_removes_entry(self):
        store = InMemoryDraftStore()
        store.set("abc", {"title": "Test"})
        store.delete("abc")
        assert store.get("abc") is None

    def test_prune_removes_stale_entries(self):
        store = InMemoryDraftStore()
        store.set(
            "old",
            {
                "title": "Old",
                "created_at": "2020-01-01T00:00:00Z",
                "created_epoch": 1577836800.0,
            },
        )
        store.set(
            "new",
            {
                "title": "New",
                "created_at": _utcnow().isoformat(),
                "created_epoch": _utcnow().timestamp(),
            },
        )
        removed = store.prune(ttl_hours=1, max_drafts=100)
        assert removed >= 1
        assert store.get("old") is None
        assert store.get("new") is not None

    def test_prune_enforces_max_drafts(self):
        store = InMemoryDraftStore()
        for i in range(15):
            store.set(
                f"draft_{i:02d}",
                {
                    "title": f"Draft {i}",
                    "created_epoch": _utcnow().timestamp() + i,
                },
            )
        removed = store.prune(ttl_hours=24, max_drafts=10)
        assert removed == 5
        assert store.count() == 10

    def test_count(self):
        store = InMemoryDraftStore()
        assert store.count() == 0
        store.set("a", {})
        assert store.count() == 1

    def test_health(self):
        store = InMemoryDraftStore()
        store.set("a", {})
        health = store.health()
        assert health["type"] == "memory"
        assert health["count"] == 1


class TestInMemoryRateLimiter:
    def test_check_allows_within_limit(self):
        limiter = InMemoryRateLimiter()
        result = limiter.check("client-1", max_hits=5, window_s=60)
        assert result["exceeded"] is False
        assert result["remaining"] == 4

    def test_check_blocks_when_exceeded(self):
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            result = limiter.check("client-1", max_hits=5, window_s=60)
        assert result["exceeded"] is False
        # 6th hit
        result = limiter.check("client-1", max_hits=5, window_s=60)
        assert result["exceeded"] is True
        assert result["remaining"] == 0

    def test_different_clients_are_isolated(self):
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.check("client-a", max_hits=5, window_s=60)
        # client-b should still be allowed
        result = limiter.check("client-b", max_hits=5, window_s=60)
        assert result["exceeded"] is False
        assert result["remaining"] == 4

    def test_health(self):
        limiter = InMemoryRateLimiter()
        limiter.check("c1", max_hits=5, window_s=60)
        health = limiter.health()
        assert health["type"] == "memory"
        assert health["bucket_count"] == 1


# ────────────────────────────────────────────────────────────
#  Persistence Layer (Factory)
# ────────────────────────────────────────────────────────────

class TestFactories:
    def test_create_draft_store_default_is_memory(self):
        from report_service_persistence import create_draft_store

        store = create_draft_store()
        assert isinstance(store, InMemoryDraftStore)

    def test_create_rate_limiter_default_is_memory(self):
        from report_service_persistence import create_rate_limiter

        limiter = create_rate_limiter()
        assert isinstance(limiter, InMemoryRateLimiter)
