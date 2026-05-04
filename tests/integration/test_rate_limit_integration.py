"""Integration tests for rate limiting and admin key management.

These tests run against the real app with a real Redis connection.
They are skipped automatically if Redis is not reachable.

Run with:
    pytest tests/integration/ -v -m integration
"""

import asyncio

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REDIS_URL = "redis://localhost:6379/1"  # DB 1 to isolate from dev data
ADMIN_KEY = "sk_admin_dev_12345"
USER_KEY = "sk_user_dev_67890"


def admin_headers() -> dict:
    return {"X-API-Key": ADMIN_KEY}


def user_headers() -> dict:
    return {"X-API-Key": USER_KEY}


# ---------------------------------------------------------------------------
# Session-scoped Redis fixture — skip entire module if Redis unreachable
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def redis_available():
    """Skip all integration tests if Redis is not running."""
    try:
        r = aioredis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        await r.ping()
        await r.aclose()
    except Exception:
        pytest.skip("Redis not reachable — skipping integration tests")


@pytest_asyncio.fixture(scope="session")
async def http_client(redis_available):
    """AsyncClient that drives the FastAPI app through its full lifespan."""
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Rate limit endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRateLimitIntegration:
    """End-to-end rate limit flow."""

    async def test_health_check(self, http_client: AsyncClient) -> None:
        response = await http_client.get(
            "/api/v1/rate-limit/health", headers=admin_headers()
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")

    async def test_check_rate_limit_allowed(self, http_client: AsyncClient) -> None:
        response = await http_client.post(
            "/api/v1/rate-limit/check",
            headers=user_headers(),
            json={
                "identifier": "integ-test-user",
                "max_requests": 100,
                "window_seconds": 60,
                "namespace": "integration",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] is True
        assert data["limit"] == 100
        assert data["remaining"] >= 0

    async def test_check_rate_limit_throttled_after_limit(
        self, http_client: AsyncClient
    ) -> None:
        identifier = "integ-throttle-test"
        # Reset first so state is clean
        await http_client.post(
            "/api/v1/rate-limit/reset",
            headers=admin_headers(),
            json={"identifier": identifier, "namespace": "integ-throttle"},
        )

        payload = {
            "identifier": identifier,
            "max_requests": 3,
            "window_seconds": 60,
            "namespace": "integ-throttle",
        }
        # Exhaust the limit
        for _ in range(3):
            r = await http_client.post(
                "/api/v1/rate-limit/check", headers=user_headers(), json=payload
            )
            assert r.status_code == 200

        # The next request must be throttled
        r = await http_client.post(
            "/api/v1/rate-limit/check", headers=user_headers(), json=payload
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is False
        assert r.json()["status"] == "throttled"
        assert r.json()["remaining"] == 0

    async def test_reset_rate_limit(self, http_client: AsyncClient) -> None:
        identifier = "integ-reset-test"
        namespace = "integ-reset"
        payload = {
            "identifier": identifier,
            "max_requests": 1,
            "window_seconds": 60,
            "namespace": namespace,
        }
        # Exhaust limit
        await http_client.post(
            "/api/v1/rate-limit/check", headers=user_headers(), json=payload
        )
        await http_client.post(
            "/api/v1/rate-limit/check", headers=user_headers(), json=payload
        )
        # Confirm throttled
        r = await http_client.post(
            "/api/v1/rate-limit/check", headers=user_headers(), json=payload
        )
        assert r.json()["allowed"] is False

        # Reset
        reset_r = await http_client.post(
            "/api/v1/rate-limit/reset",
            headers=admin_headers(),
            json={"identifier": identifier, "namespace": namespace},
        )
        assert reset_r.status_code == 204

        # Should be allowed again
        r = await http_client.post(
            "/api/v1/rate-limit/check", headers=user_headers(), json=payload
        )
        assert r.json()["allowed"] is True

    async def test_reset_requires_admin(self, http_client: AsyncClient) -> None:
        response = await http_client.post(
            "/api/v1/rate-limit/reset",
            headers=user_headers(),
            json={"identifier": "someone", "namespace": "ns"},
        )
        assert response.status_code == 403

    async def test_check_requires_auth(self, http_client: AsyncClient) -> None:
        response = await http_client.post(
            "/api/v1/rate-limit/check",
            json={"identifier": "x", "max_requests": 10, "window_seconds": 60},
        )
        assert response.status_code == 401

    async def test_usage_endpoint(self, http_client: AsyncClient) -> None:
        identifier = "integ-usage-test"
        await http_client.post(
            "/api/v1/rate-limit/check",
            headers=user_headers(),
            json={
                "identifier": identifier,
                "max_requests": 10,
                "window_seconds": 60,
                "namespace": "integ-usage",
            },
        )
        r = await http_client.get(
            f"/api/v1/rate-limit/usage/{identifier}",
            headers=admin_headers(),
            params={"namespace": "integ-usage"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["identifier"] == identifier
        assert data["current_count"] >= 1


# ---------------------------------------------------------------------------
# Admin key management integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAdminKeysIntegration:
    """End-to-end API key management via /admin/keys."""

    async def test_list_keys_as_admin(self, http_client: AsyncClient) -> None:
        r = await http_client.get("/api/v1/admin/keys", headers=admin_headers())
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_list_keys_requires_admin(self, http_client: AsyncClient) -> None:
        r = await http_client.get("/api/v1/admin/keys", headers=user_headers())
        assert r.status_code == 403

    async def test_create_list_get_revoke_key(self, http_client: AsyncClient) -> None:
        # Create
        create_r = await http_client.post(
            "/api/v1/admin/keys",
            headers=admin_headers(),
            json={"name": "Integration Test Key", "role": "user"},
        )
        assert create_r.status_code == 201
        created = create_r.json()
        assert "key" in created
        assert created["key"].startswith("sk_")
        key_id = created["key_id"]

        # Get by ID
        get_r = await http_client.get(
            f"/api/v1/admin/keys/{key_id}", headers=admin_headers()
        )
        assert get_r.status_code == 200
        assert get_r.json()["key_id"] == key_id
        assert get_r.json()["is_active"] is True

        # New key should authenticate
        auth_r = await http_client.get(
            "/api/v1/rate-limit/health", headers={"X-API-Key": created["key"]}
        )
        assert auth_r.status_code == 200

        # Revoke
        del_r = await http_client.delete(
            f"/api/v1/admin/keys/{key_id}", headers=admin_headers()
        )
        assert del_r.status_code == 204

        # Key should now be rejected
        auth_r2 = await http_client.get(
            "/api/v1/rate-limit/health", headers={"X-API-Key": created["key"]}
        )
        assert auth_r2.status_code == 401

    async def test_get_nonexistent_key_returns_404(self, http_client: AsyncClient) -> None:
        r = await http_client.get(
            "/api/v1/admin/keys/nonexistent_key_id", headers=admin_headers()
        )
        assert r.status_code == 404

    async def test_revoke_nonexistent_key_returns_404(self, http_client: AsyncClient) -> None:
        r = await http_client.delete(
            "/api/v1/admin/keys/nonexistent_key_id", headers=admin_headers()
        )
        assert r.status_code == 404

    async def test_create_key_with_role_restriction(self, http_client: AsyncClient) -> None:
        """READONLY key can only access read endpoints, not write."""
        create_r = await http_client.post(
            "/api/v1/admin/keys",
            headers=admin_headers(),
            json={"name": "Readonly Integration Key", "role": "readonly"},
        )
        assert create_r.status_code == 201
        ro_key = create_r.json()["key"]
        key_id = create_r.json()["key_id"]

        # READONLY can access health
        health_r = await http_client.get(
            "/api/v1/rate-limit/health", headers={"X-API-Key": ro_key}
        )
        assert health_r.status_code == 200

        # READONLY cannot POST /check (requires USER)
        check_r = await http_client.post(
            "/api/v1/rate-limit/check",
            headers={"X-API-Key": ro_key},
            json={"identifier": "x", "max_requests": 10, "window_seconds": 60},
        )
        assert check_r.status_code == 403

        # Cleanup
        await http_client.delete(f"/api/v1/admin/keys/{key_id}", headers=admin_headers())
