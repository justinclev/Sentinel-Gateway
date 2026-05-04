"""Unit tests for rate limit service."""

import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.rate_limit_service import RateLimitService
from app.domain.rate_limit import RateLimitConfig, RateLimitRepository, RateLimitResult, RateLimitStatus


@pytest.fixture
def mock_repository() -> RateLimitRepository:
    """Create a mock repository."""
    return AsyncMock(spec=RateLimitRepository)


@pytest.fixture
def service(mock_repository: RateLimitRepository) -> RateLimitService:
    """Create service with mock repository."""
    logger = logging.getLogger("test")
    return RateLimitService(mock_repository, logger)


class TestRateLimitService:
    """Tests for rate limit service."""

    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(
        self, service: RateLimitService, mock_repository: RateLimitRepository
    ) -> None:
        """Test checking rate limit when allowed."""
        mock_result = RateLimitResult(
            status=RateLimitStatus.ALLOWED,
            identifier="user123",
            limit=10,
            remaining=5,
            reset_at=datetime.now(),
            retry_after=None
        )
        mock_repository.check_rate_limit.return_value = mock_result

        result = await service.check_rate_limit(
            identifier="user123",
            max_requests=10,
            window_seconds=60,
            namespace="api"
        )

        assert result.status == RateLimitStatus.ALLOWED
        assert result.remaining == 5
        mock_repository.check_rate_limit.assert_called_once()

        # Verify config was created correctly
        call_args = mock_repository.check_rate_limit.call_args[0][0]
        assert isinstance(call_args, RateLimitConfig)
        assert call_args.identifier == "user123"
        assert call_args.max_requests == 10
        assert call_args.window_seconds == 60
        assert call_args.namespace == "api"

    @pytest.mark.asyncio
    async def test_check_rate_limit_throttled(
        self, service: RateLimitService, mock_repository: RateLimitRepository
    ) -> None:
        """Test checking rate limit when throttled."""
        mock_result = RateLimitResult(
            status=RateLimitStatus.THROTTLED,
            identifier="user123",
            limit=10,
            remaining=0,
            reset_at=datetime.now(),
            retry_after=30
        )
        mock_repository.check_rate_limit.return_value = mock_result

        result = await service.check_rate_limit(
            identifier="user123",
            max_requests=10,
            window_seconds=60
        )

        assert result.status == RateLimitStatus.THROTTLED
        assert result.remaining == 0
        assert result.retry_after == 30

    @pytest.mark.asyncio
    async def test_check_rate_limit_default_namespace(
        self, service: RateLimitService, mock_repository: RateLimitRepository
    ) -> None:
        """Test default namespace is used."""
        mock_result = RateLimitResult(
            status=RateLimitStatus.ALLOWED,
            identifier="user123",
            limit=10,
            remaining=5,
            reset_at=datetime.now(),
            retry_after=None
        )
        mock_repository.check_rate_limit.return_value = mock_result

        await service.check_rate_limit(
            identifier="user123",
            max_requests=10,
            window_seconds=60
        )

        call_args = mock_repository.check_rate_limit.call_args[0][0]
        assert call_args.namespace == "default"

    @pytest.mark.asyncio
    async def test_reset_rate_limit_success(
        self, service: RateLimitService, mock_repository: RateLimitRepository
    ) -> None:
        """Test successful rate limit reset."""
        mock_repository.reset_rate_limit.return_value = True

        result = await service.reset_rate_limit("user123", "api")

        assert result is True
        mock_repository.reset_rate_limit.assert_called_once_with("user123", "api")

    @pytest.mark.asyncio
    async def test_reset_rate_limit_failure(
        self, service: RateLimitService, mock_repository: RateLimitRepository
    ) -> None:
        """Test failed rate limit reset."""
        mock_repository.reset_rate_limit.return_value = False

        result = await service.reset_rate_limit("user123", "api")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_usage(
        self, service: RateLimitService, mock_repository: RateLimitRepository
    ) -> None:
        """Test getting usage statistics."""
        mock_repository.get_current_usage.return_value = (5, 1234567890)

        result = await service.get_usage("user123", "api")

        assert result["current_count"] == 5
        assert result["window_start"] == 1234567890
        mock_repository.get_current_usage.assert_called_once_with("user123", "api")

    @pytest.mark.asyncio
    async def test_health_check(
        self, service: RateLimitService, mock_repository: RateLimitRepository
    ) -> None:
        """Test health check."""
        mock_repository.health_check.return_value = True

        result = await service.health_check()

        assert result is True
        mock_repository.health_check.assert_called_once()
