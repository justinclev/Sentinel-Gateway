"""Unit tests for rate limit domain models."""

from datetime import datetime

import pytest

from app.domain.rate_limit import RateLimitConfig, RateLimitResult, RateLimitStatus


class TestRateLimitConfig:
    """Tests for RateLimitConfig validation."""

    def test_valid_config(self) -> None:
        """Test creating a valid rate limit config."""
        config = RateLimitConfig(
            identifier="user123", max_requests=100, window_seconds=60, namespace="api"
        )
        assert config.identifier == "user123"
        assert config.max_requests == 100
        assert config.window_seconds == 60
        assert config.namespace == "api"

    def test_default_namespace(self) -> None:
        """Test default namespace is 'default'."""
        config = RateLimitConfig(identifier="user123", max_requests=100, window_seconds=60)
        assert config.namespace == "default"

    def test_zero_max_requests_raises_error(self) -> None:
        """Test zero max_requests raises ValueError."""
        with pytest.raises(ValueError, match="max_requests must be greater than 0"):
            RateLimitConfig(identifier="user123", max_requests=0, window_seconds=60)

    def test_negative_max_requests_raises_error(self) -> None:
        """Test negative max_requests raises ValueError."""
        with pytest.raises(ValueError, match="max_requests must be greater than 0"):
            RateLimitConfig(identifier="user123", max_requests=-5, window_seconds=60)

    def test_zero_window_seconds_raises_error(self) -> None:
        """Test zero window_seconds raises ValueError."""
        with pytest.raises(ValueError, match="window_seconds must be greater than 0"):
            RateLimitConfig(identifier="user123", max_requests=100, window_seconds=0)

    def test_negative_window_seconds_raises_error(self) -> None:
        """Test negative window_seconds raises ValueError."""
        with pytest.raises(ValueError, match="window_seconds must be greater than 0"):
            RateLimitConfig(identifier="user123", max_requests=100, window_seconds=-10)

    def test_empty_identifier_raises_error(self) -> None:
        """Test empty identifier raises ValueError."""
        with pytest.raises(ValueError, match="identifier cannot be empty"):
            RateLimitConfig(identifier="", max_requests=100, window_seconds=60)


class TestRateLimitResult:
    """Tests for RateLimitResult."""

    def test_allowed_result(self) -> None:
        """Test creating an allowed result."""
        result = RateLimitResult(
            status=RateLimitStatus.ALLOWED,
            identifier="user123",
            limit=100,
            remaining=50,
            reset_at=datetime.now(),
            retry_after=None,
        )
        assert result.status == RateLimitStatus.ALLOWED
        assert result.is_allowed is True
        assert result.is_throttled is False

    def test_throttled_result(self) -> None:
        """Test creating a throttled result."""
        result = RateLimitResult(
            status=RateLimitStatus.THROTTLED,
            identifier="user123",
            limit=100,
            remaining=0,
            reset_at=datetime.now(),
            retry_after=30,
        )
        assert result.status == RateLimitStatus.THROTTLED
        assert result.is_allowed is False
        assert result.is_throttled is True
        assert result.retry_after == 30

    def test_immutable_result(self) -> None:
        """Test that RateLimitResult is frozen (immutable)."""
        result = RateLimitResult(
            status=RateLimitStatus.ALLOWED,
            identifier="user123",
            limit=100,
            remaining=50,
            reset_at=datetime.now(),
            retry_after=None,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.remaining = 25  # type: ignore
