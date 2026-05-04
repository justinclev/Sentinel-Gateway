"""Test configuration and fixtures."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.infrastructure.redis.client import RedisClient
from app.infrastructure.redis.rate_limit_repository import RedisRateLimitRepository
from main import app


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio backend for async tests."""
    return "asyncio"


@pytest.fixture
async def client() -> AsyncClient:
    """Create test HTTP client."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_redis_client() -> RedisClient:
    """Create a mock Redis client for testing."""
    mock_client = MagicMock(spec=RedisClient)
    mock_redis = AsyncMock()
    mock_client.client = mock_redis
    mock_client.health_check = AsyncMock(return_value=True)
    return mock_client


@pytest.fixture
def mock_repository(mock_redis_client: RedisClient) -> RedisRateLimitRepository:
    """Create a mock rate limit repository."""
    return AsyncMock(spec=RedisRateLimitRepository)
