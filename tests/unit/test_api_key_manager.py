"""Unit tests for APIKeyManager."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.gateway.models import APIKey, APIKeyRole
from app.infrastructure.security.api_keys import (
    APIKeyManager,
    get_api_key_manager,
    set_api_key_manager,
)


def _make_api_key(
    key_id: str = "test_001",
    role: APIKeyRole = APIKeyRole.USER,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> APIKey:
    return APIKey(
        key_id=key_id,
        key_hash="abc123hash",
        name="Test Key",
        role=role,
        created_at=datetime(2026, 1, 1),
        is_active=is_active,
        expires_at=expires_at,
    )


@pytest.fixture
def mock_repository():
    repo = MagicMock()
    repo.get_by_hash = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.list_all = AsyncMock()
    return repo


@pytest.fixture
def manager(mock_repository):
    return APIKeyManager(mock_repository)


class TestValidateKey:
    @pytest.mark.asyncio
    async def test_valid_key_returns_api_key(self, manager, mock_repository):
        api_key = _make_api_key()
        mock_repository.get_by_hash.return_value = api_key

        result = await manager.validate_key("sk_somekey")
        assert result == api_key

    @pytest.mark.asyncio
    async def test_unknown_key_returns_none(self, manager, mock_repository):
        mock_repository.get_by_hash.return_value = None

        result = await manager.validate_key("sk_unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_inactive_key_returns_none(self, manager, mock_repository):
        mock_repository.get_by_hash.return_value = _make_api_key(is_active=False)

        result = await manager.validate_key("sk_revoked")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_key_returns_none(self, manager, mock_repository):
        expired = _make_api_key(expires_at=datetime(2020, 1, 1))
        mock_repository.get_by_hash.return_value = expired

        result = await manager.validate_key("sk_expired")
        assert result is None

    @pytest.mark.asyncio
    async def test_unexpired_key_is_valid(self, manager, mock_repository):
        future = _make_api_key(expires_at=datetime(2099, 1, 1))
        mock_repository.get_by_hash.return_value = future

        result = await manager.validate_key("sk_future")
        assert result is not None


class TestCreateKey:
    @pytest.mark.asyncio
    async def test_create_key_returns_plain_key_and_api_key(self, manager, mock_repository):
        stored_key = _make_api_key()
        mock_repository.create.return_value = stored_key

        plain_key, api_key = await manager.create_key(name="Test", role=APIKeyRole.USER)

        assert plain_key.startswith("sk_")
        assert api_key == stored_key
        mock_repository.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_key_stores_hash_not_plain(self, manager, mock_repository):
        mock_repository.create.return_value = _make_api_key()

        plain_key, _ = await manager.create_key(name="Test", role=APIKeyRole.ADMIN)

        stored_key_obj = mock_repository.create.call_args[0][0]
        # The stored key_hash must NOT equal the plain key
        assert stored_key_obj.key_hash != plain_key
        # Must be a 64-char SHA-256 hex
        assert len(stored_key_obj.key_hash) == 64

    @pytest.mark.asyncio
    async def test_create_key_with_metadata(self, manager, mock_repository):
        mock_repository.create.return_value = _make_api_key()

        await manager.create_key(
            name="Svc Key", role=APIKeyRole.USER, metadata={"service": "billing"}
        )
        stored = mock_repository.create.call_args[0][0]
        assert stored.metadata == {"service": "billing"}


class TestRevokeByKey:
    @pytest.mark.asyncio
    async def test_revoke_existing_key(self, manager, mock_repository):
        api_key = _make_api_key()
        mock_repository.get_by_hash.return_value = api_key

        result = await manager.revoke_key("sk_torevoke")

        assert result is True
        mock_repository.update.assert_called_once()
        updated = mock_repository.update.call_args[0][0]
        assert updated.is_active is False

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self, manager, mock_repository):
        mock_repository.get_by_hash.return_value = None

        result = await manager.revoke_key("sk_ghost")
        assert result is False
        mock_repository.update.assert_not_called()


class TestRevokeById:
    @pytest.mark.asyncio
    async def test_revoke_by_id_existing(self, manager, mock_repository):
        api_key = _make_api_key(key_id="key_001")
        mock_repository.get_by_id.return_value = api_key

        result = await manager.revoke_by_id("key_001")

        assert result is True
        mock_repository.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_by_id_not_found(self, manager, mock_repository):
        mock_repository.get_by_id.return_value = None

        result = await manager.revoke_by_id("ghost_id")
        assert result is False


class TestListKeys:
    @pytest.mark.asyncio
    async def test_list_keys_delegates_to_repository(self, manager, mock_repository):
        keys = [_make_api_key("a"), _make_api_key("b")]
        mock_repository.list_all.return_value = keys

        result = await manager.list_keys()
        assert result == keys


class TestGlobalManager:
    def test_get_before_set_raises(self):
        import app.infrastructure.security.api_keys as mod

        original = mod._api_key_manager
        mod._api_key_manager = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                get_api_key_manager()
        finally:
            mod._api_key_manager = original

    def test_set_and_get(self):
        import app.infrastructure.security.api_keys as mod

        original = mod._api_key_manager
        fake_manager = MagicMock(spec=APIKeyManager)
        try:
            set_api_key_manager(fake_manager)
            assert get_api_key_manager() is fake_manager
        finally:
            mod._api_key_manager = original
