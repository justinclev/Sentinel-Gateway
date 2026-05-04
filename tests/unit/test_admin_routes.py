"""Unit tests for the admin /keys endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.domain.gateway.models import APIKey, APIKeyRole


def _make_api_key(
    key_id: str = "admin_test",
    role: APIKeyRole = APIKeyRole.ADMIN,
    is_active: bool = True,
) -> APIKey:
    return APIKey(
        key_id=key_id,
        key_hash="fakehash",
        name="Test Key",
        role=role,
        created_at=datetime(2026, 1, 1),
        is_active=is_active,
    )


@pytest.fixture
def mock_manager():
    mgr = MagicMock()
    mgr.create_key = AsyncMock()
    mgr.list_keys = AsyncMock()
    mgr.revoke_by_id = AsyncMock()
    mgr.repository = MagicMock()
    mgr.repository.get_by_id = AsyncMock()
    return mgr


@pytest.fixture
def admin_client(mock_manager):
    """TestClient with auth and manager overridden to admin-level."""
    from app.presentation.api.admin_routes import get_manager
    from app.presentation.api.security import verify_api_key
    from main import app

    app.dependency_overrides[verify_api_key] = lambda: _make_api_key()
    app.dependency_overrides[get_manager] = lambda: mock_manager

    yield TestClient(app, raise_server_exceptions=False)

    app.dependency_overrides.clear()


@pytest.fixture
def user_client(mock_manager):
    """TestClient with USER-role auth — should fail admin-only endpoints."""
    from app.presentation.api.admin_routes import get_manager
    from app.presentation.api.security import verify_api_key
    from main import app

    app.dependency_overrides[verify_api_key] = lambda: _make_api_key(role=APIKeyRole.USER)
    app.dependency_overrides[get_manager] = lambda: mock_manager

    yield TestClient(app, raise_server_exceptions=False)

    app.dependency_overrides.clear()


class TestCreateKey:
    def test_create_key_returns_201_with_plain_key(self, admin_client, mock_manager):
        plain_key = "sk_abc123"
        created = _make_api_key(key_id="new_001")
        mock_manager.create_key.return_value = (plain_key, created)

        r = admin_client.post(
            "/api/v1/admin/keys",
            json={"name": "My Key", "role": "user"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["key"] == plain_key
        assert data["key_id"] == "new_001"
        assert data["role"] == "admin"  # from _make_api_key default

    def test_create_key_calls_manager_with_correct_args(self, admin_client, mock_manager):
        mock_manager.create_key.return_value = ("sk_x", _make_api_key())

        admin_client.post(
            "/api/v1/admin/keys",
            json={"name": "Test", "role": "readonly", "rate_limit": 100},
        )
        mock_manager.create_key.assert_called_once()
        call_kwargs = mock_manager.create_key.call_args.kwargs
        assert call_kwargs["name"] == "Test"
        assert call_kwargs["role"] == APIKeyRole.READONLY
        assert call_kwargs["rate_limit"] == 100

    def test_create_key_requires_admin(self, user_client):
        r = user_client.post("/api/v1/admin/keys", json={"name": "X", "role": "user"})
        assert r.status_code == 403

    def test_create_key_missing_name_returns_422(self, admin_client):
        r = admin_client.post("/api/v1/admin/keys", json={"role": "user"})
        assert r.status_code == 422

    def test_create_key_invalid_role_returns_422(self, admin_client):
        r = admin_client.post("/api/v1/admin/keys", json={"name": "X", "role": "superadmin"})
        assert r.status_code == 422


class TestListKeys:
    def test_list_keys_returns_200_and_list(self, admin_client, mock_manager):
        mock_manager.list_keys.return_value = [
            _make_api_key("key_001", APIKeyRole.ADMIN),
            _make_api_key("key_002", APIKeyRole.USER),
        ]

        r = admin_client.get("/api/v1/admin/keys")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        assert data[0]["key_id"] == "key_001"
        assert data[1]["key_id"] == "key_002"

    def test_list_keys_empty(self, admin_client, mock_manager):
        mock_manager.list_keys.return_value = []
        r = admin_client.get("/api/v1/admin/keys")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_keys_no_plain_key_in_response(self, admin_client, mock_manager):
        mock_manager.list_keys.return_value = [_make_api_key()]
        r = admin_client.get("/api/v1/admin/keys")
        # KeySummary must NOT contain 'key' or 'key_hash'
        item = r.json()[0]
        assert "key" not in item
        assert "key_hash" not in item

    def test_list_keys_requires_admin(self, user_client):
        r = user_client.get("/api/v1/admin/keys")
        assert r.status_code == 403


class TestGetKey:
    def test_get_existing_key(self, admin_client, mock_manager):
        mock_manager.repository.get_by_id.return_value = _make_api_key("key_abc")

        r = admin_client.get("/api/v1/admin/keys/key_abc")
        assert r.status_code == 200
        assert r.json()["key_id"] == "key_abc"

    def test_get_nonexistent_key_returns_404(self, admin_client, mock_manager):
        mock_manager.repository.get_by_id.return_value = None

        r = admin_client.get("/api/v1/admin/keys/does_not_exist")
        assert r.status_code == 404

    def test_get_key_requires_admin(self, user_client):
        r = user_client.get("/api/v1/admin/keys/some_id")
        assert r.status_code == 403


class TestRevokeKey:
    def test_revoke_existing_key_returns_204(self, admin_client, mock_manager):
        mock_manager.revoke_by_id.return_value = True

        r = admin_client.delete("/api/v1/admin/keys/key_to_revoke")
        assert r.status_code == 204
        mock_manager.revoke_by_id.assert_called_once_with("key_to_revoke")

    def test_revoke_nonexistent_key_returns_404(self, admin_client, mock_manager):
        mock_manager.revoke_by_id.return_value = False

        r = admin_client.delete("/api/v1/admin/keys/ghost_key")
        assert r.status_code == 404

    def test_revoke_requires_admin(self, user_client):
        r = user_client.delete("/api/v1/admin/keys/any_id")
        assert r.status_code == 403
