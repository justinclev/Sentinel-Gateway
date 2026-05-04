"""Unit tests for the Redis API key repository."""

import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.domain.gateway.models import APIKey, APIKeyRole
from app.infrastructure.security.redis_repository import RedisAPIKeyRepository


def _make_api_key(key_id: str = "test_001", role: APIKeyRole = APIKeyRole.USER) -> APIKey:
    return APIKey(
        key_id=key_id,
        key_hash="abc123hash",
        name="Test Key",
        role=role,
        created_at=datetime(2026, 1, 1),
        metadata={"env": "test"},
    )


def _serialize(api_key: APIKey) -> str:
    return json.dumps(
        {
            "key_id": api_key.key_id,
            "name": api_key.name,
            "role": api_key.role.value,
            "created_at": api_key.created_at.isoformat(),
            "expires_at": None,
            "is_active": api_key.is_active,
            "rate_limit": api_key.rate_limit,
            "metadata": api_key.metadata or {},
        }
    )


@pytest.fixture
def mock_redis():
    """Async Redis mock."""
    r = AsyncMock()
    return r


@pytest.fixture
def repository(mock_redis):
    return RedisAPIKeyRepository(mock_redis)


class TestGetByHash:
    @pytest.mark.asyncio
    async def test_returns_api_key_when_found(self, repository, mock_redis):
        api_key = _make_api_key()
        mock_redis.get = AsyncMock(return_value=_serialize(api_key))

        result = await repository.get_by_hash("abc123hash")

        assert result is not None
        assert result.key_id == "test_001"
        assert result.role == APIKeyRole.USER
        assert result.key_hash == "abc123hash"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, repository, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)

        result = await repository.get_by_hash("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_makes_correct_redis_key(self, repository, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)

        await repository.get_by_hash("myhash")
        mock_redis.get.assert_called_once_with("apikey:myhash")


class TestCreate:
    @pytest.mark.asyncio
    async def test_stores_key_in_redis(self, repository, mock_redis):
        api_key = _make_api_key()
        mock_redis.setex = AsyncMock()

        result = await repository.create(api_key)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        redis_key, ttl, payload = call_args[0]
        assert redis_key == "apikey:abc123hash"
        assert ttl > 0
        stored = json.loads(payload)
        assert stored["key_id"] == "test_001"
        assert stored["role"] == "user"
        assert result == api_key

    @pytest.mark.asyncio
    async def test_custom_ttl_is_used(self, repository, mock_redis):
        mock_redis.setex = AsyncMock()

        await repository.create(_make_api_key(), ttl_seconds=3600)

        _, ttl, _ = mock_redis.setex.call_args[0]
        assert ttl == 3600


class TestUpdate:
    @pytest.mark.asyncio
    async def test_preserves_existing_ttl(self, repository, mock_redis):
        api_key = _make_api_key()
        mock_redis.ttl = AsyncMock(return_value=7200)
        mock_redis.setex = AsyncMock()

        await repository.update(api_key)

        _, ttl, _ = mock_redis.setex.call_args[0]
        assert ttl == 7200

    @pytest.mark.asyncio
    async def test_uses_default_ttl_when_key_missing(self, repository, mock_redis):
        api_key = _make_api_key()
        mock_redis.ttl = AsyncMock(return_value=-2)  # key does not exist
        mock_redis.setex = AsyncMock()

        await repository.update(api_key)

        _, ttl, _ = mock_redis.setex.call_args[0]
        assert ttl == RedisAPIKeyRepository.TTL_DAYS * 86400


class TestDelete:
    @pytest.mark.asyncio
    async def test_deletes_and_returns_true(self, repository, mock_redis):
        mock_redis.delete = AsyncMock(return_value=1)

        result = await repository.delete("abc123hash")

        assert result is True
        mock_redis.delete.assert_called_once_with("apikey:abc123hash")

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self, repository, mock_redis):
        mock_redis.delete = AsyncMock(return_value=0)

        result = await repository.delete("nonexistent")
        assert result is False


class TestGetById:
    @pytest.mark.asyncio
    async def test_finds_key_by_id(self, repository, mock_redis):
        api_key = _make_api_key(key_id="target_key")

        async def scan_iter(match, count):
            yield "apikey:abc123hash"

        mock_redis.scan_iter = scan_iter
        mock_redis.get = AsyncMock(return_value=_serialize(api_key))

        result = await repository.get_by_id("target_key")

        assert result is not None
        assert result.key_id == "target_key"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, repository, mock_redis):
        async def scan_iter(match, count):
            yield "apikey:abc123hash"

        api_key = _make_api_key(key_id="other_key")
        mock_redis.scan_iter = scan_iter
        mock_redis.get = AsyncMock(return_value=_serialize(api_key))

        result = await repository.get_by_id("missing_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_keys(self, repository, mock_redis):
        async def scan_iter(match, count):
            return
            yield

        mock_redis.scan_iter = scan_iter

        result = await repository.get_by_id("any_id")
        assert result is None


class TestListAll:
    @pytest.mark.asyncio
    async def test_returns_all_keys(self, repository, mock_redis):
        key1 = _make_api_key("key1", APIKeyRole.ADMIN)
        key2 = _make_api_key("key2", APIKeyRole.USER)

        redis_data = {
            "apikey:hash1": _serialize(key1),
            "apikey:hash2": _serialize(key2),
        }

        async def scan_iter(match, count):
            for k in redis_data:
                yield k

        mock_redis.scan_iter = scan_iter
        mock_redis.get = AsyncMock(side_effect=lambda k: redis_data.get(k))

        result = await repository.list_all()
        assert len(result) == 2
        ids = {k.key_id for k in result}
        assert ids == {"key1", "key2"}

    @pytest.mark.asyncio
    async def test_empty_when_no_keys(self, repository, mock_redis):
        async def scan_iter(match, count):
            return
            yield

        mock_redis.scan_iter = scan_iter

        result = await repository.list_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_none_values(self, repository, mock_redis):
        async def scan_iter(match, count):
            yield "apikey:hash1"

        mock_redis.scan_iter = scan_iter
        mock_redis.get = AsyncMock(return_value=None)

        result = await repository.list_all()
        assert result == []
