"""Unit tests for Redis rate limit repository."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import RedisError

from app.domain.rate_limit import RateLimitConfig, RateLimitStatus
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.redis.rate_limit_repository import RedisRateLimitRepository


@pytest.fixture
def mock_redis_client() -> RedisClient:
    """Create a mock Redis client."""
    mock_client = MagicMock(spec=RedisClient)
    mock_redis = AsyncMock()
    mock_client.client = mock_redis
    return mock_client


@pytest.fixture
def repository(mock_redis_client: RedisClient) -> RedisRateLimitRepository:
    """Create repository with mock Redis client."""
    return RedisRateLimitRepository(mock_redis_client, key_prefix="test_rate_limit")


class TestRedisRateLimitRepository:
    """Tests for Redis rate limit repository."""

    def test_get_key(self, repository: RedisRateLimitRepository) -> None:
        """Test Redis key generation."""
        key = repository._get_key("user123", "api")
        assert key == "test_rate_limit:api:user123"

    @pytest.mark.asyncio
    async def test_check_rate_limit_first_request(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test first request is allowed."""
        # Setup mock - no existing count
        mock_redis = mock_redis_client.client
        mock_redis.get.return_value = None

        # Create proper mock pipeline
        mock_pipeline = MagicMock()
        mock_pipeline.incr = MagicMock()
        mock_pipeline.expire = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[1, True])
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        config = RateLimitConfig(
            identifier="user123", max_requests=5, window_seconds=60, namespace="api"
        )

        result = await repository.check_rate_limit(config)

        assert result.status == RateLimitStatus.ALLOWED
        assert result.limit == 5
        assert result.remaining == 4  # 5 - 0 - 1
        assert result.identifier == "user123"
        assert result.retry_after is None

    @pytest.mark.asyncio
    async def test_check_rate_limit_within_limit(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test request within limit is allowed."""
        mock_redis = mock_redis_client.client
        mock_redis.get.return_value = "3"  # 3 requests already made

        # Create proper mock pipeline
        mock_pipeline = MagicMock()
        mock_pipeline.incr = MagicMock()
        mock_pipeline.expire = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[4, True])
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        config = RateLimitConfig(
            identifier="user123", max_requests=5, window_seconds=60, namespace="api"
        )

        result = await repository.check_rate_limit(config)

        assert result.status == RateLimitStatus.ALLOWED
        assert result.remaining == 1  # 5 - 3 - 1
        mock_pipeline.incr.assert_called_once()
        mock_pipeline.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_rate_limit_at_limit(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test request at limit is throttled."""
        mock_redis = mock_redis_client.client
        mock_redis.get.return_value = "5"  # Already at limit

        config = RateLimitConfig(
            identifier="user123", max_requests=5, window_seconds=60, namespace="api"
        )

        result = await repository.check_rate_limit(config)

        assert result.status == RateLimitStatus.THROTTLED
        assert result.remaining == 0
        assert result.retry_after is not None
        assert result.retry_after > 0
        # Should not increment when throttled
        mock_redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_rate_limit_over_limit(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test request over limit is throttled."""
        mock_redis = mock_redis_client.client
        mock_redis.get.return_value = "10"  # Way over limit

        config = RateLimitConfig(
            identifier="user123", max_requests=5, window_seconds=60, namespace="api"
        )

        result = await repository.check_rate_limit(config)

        assert result.status == RateLimitStatus.THROTTLED
        assert result.remaining == 0

    @pytest.mark.asyncio
    async def test_check_rate_limit_redis_error_fails_open(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test Redis error causes fail-open (allows request)."""
        mock_redis = mock_redis_client.client
        mock_redis.get.side_effect = RedisError("Connection failed")

        config = RateLimitConfig(
            identifier="user123", max_requests=5, window_seconds=60, namespace="api"
        )

        result = await repository.check_rate_limit(config)

        # Should allow request despite error (fail open)
        assert result.status == RateLimitStatus.ALLOWED
        assert result.limit == 5
        assert result.remaining == 5

    @pytest.mark.asyncio
    async def test_reset_rate_limit(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test resetting rate limit."""
        mock_redis = mock_redis_client.client

        # Create async generator for scan_iter
        async def mock_scan(match):
            yield "test_rate_limit:api:user123:12345"

        mock_redis.scan_iter = mock_scan
        mock_redis.delete.return_value = 1

        result = await repository.reset_rate_limit("user123", "api")

        assert result is True
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_rate_limit_no_keys(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test resetting when no keys exist."""
        mock_redis = mock_redis_client.client

        # Create empty async generator
        async def mock_scan(match):
            return
            yield  # Make it a generator

        mock_redis.scan_iter = mock_scan

        result = await repository.reset_rate_limit("user123", "api")

        assert result is True
        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_reset_rate_limit_redis_error(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test reset with Redis error."""
        mock_redis = mock_redis_client.client

        # Make scan_iter raise an error immediately
        def mock_scan_error(match):
            raise RedisError("Connection failed")

        mock_redis.scan_iter = mock_scan_error

        result = await repository.reset_rate_limit("user123", "api")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_current_usage(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test getting current usage."""
        mock_redis = mock_redis_client.client

        # Create async generator
        async def mock_scan(match):
            yield "test_rate_limit:api:user123:1234567890"

        mock_redis.scan_iter = mock_scan
        mock_redis.get.return_value = "5"

        count, window = await repository.get_current_usage("user123", "api")

        assert count == 5
        assert window == 1234567890

    @pytest.mark.asyncio
    async def test_health_check(
        self, repository: RedisRateLimitRepository, mock_redis_client: RedisClient
    ) -> None:
        """Test health check delegates to client."""
        mock_redis_client.health_check = AsyncMock(return_value=True)

        result = await repository.health_check()

        assert result is True
        mock_redis_client.health_check.assert_called_once()
