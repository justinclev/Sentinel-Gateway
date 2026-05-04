"""Unit tests for API routes."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.domain.rate_limit import RateLimitResult, RateLimitStatus


@pytest.fixture
def mock_service():
    """Create a mock rate limit service."""
    return AsyncMock()


@pytest.fixture
def client_with_mock_service(mock_service):
    """Create test client with mocked service and disabled lifespan."""
    # Import here to avoid circular imports
    from app.presentation.api.dependencies import get_rate_limit_service
    from main import app

    # Override the dependency
    app.dependency_overrides[get_rate_limit_service] = lambda: mock_service

    # Create client without triggering lifespan events
    client = TestClient(app, raise_server_exceptions=False)

    yield client

    # Cleanup
    app.dependency_overrides.clear()


class TestRateLimitRoutes:
    """Tests for rate limit API routes."""

    def test_check_rate_limit_allowed(self, client_with_mock_service, mock_service):
        """Test rate limit check endpoint when allowed."""
        mock_result = RateLimitResult(
            status=RateLimitStatus.ALLOWED,
            identifier="user123",
            limit=10,
            remaining=5,
            reset_at=datetime(2026, 5, 4, 12, 0, 0),
            retry_after=None,
        )
        mock_service.check_rate_limit.return_value = mock_result

        response = client_with_mock_service.post(
            "/api/v1/rate-limit/check",
            json={
                "identifier": "user123",
                "max_requests": 10,
                "window_seconds": 60,
                "namespace": "api",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] is True
        assert data["status"] == "allowed"
        assert data["identifier"] == "user123"
        assert data["limit"] == 10
        assert data["remaining"] == 5
        assert "reset_at" in data
        assert data["retry_after"] is None

    def test_check_rate_limit_throttled(self, client_with_mock_service, mock_service):
        """Test rate limit check endpoint when throttled."""
        mock_result = RateLimitResult(
            status=RateLimitStatus.THROTTLED,
            identifier="user123",
            limit=10,
            remaining=0,
            reset_at=datetime(2026, 5, 4, 12, 0, 0),
            retry_after=45,
        )
        mock_service.check_rate_limit.return_value = mock_result

        response = client_with_mock_service.post(
            "/api/v1/rate-limit/check",
            json={
                "identifier": "user123",
                "max_requests": 10,
                "window_seconds": 60,
                "namespace": "api",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] is False
        assert data["status"] == "throttled"
        assert data["remaining"] == 0
        assert data["retry_after"] == 45

    def test_check_rate_limit_invalid_max_requests(self, client_with_mock_service):
        """Test validation for invalid max_requests."""
        response = client_with_mock_service.post(
            "/api/v1/rate-limit/check",
            json={"identifier": "user123", "max_requests": 0, "window_seconds": 60},  # Invalid
        )

        assert response.status_code == 422  # Validation error

    def test_check_rate_limit_invalid_window_seconds(self, client_with_mock_service):
        """Test validation for invalid window_seconds."""
        response = client_with_mock_service.post(
            "/api/v1/rate-limit/check",
            json={"identifier": "user123", "max_requests": 10, "window_seconds": -5},  # Invalid
        )

        assert response.status_code == 422  # Validation error

    def test_check_rate_limit_missing_identifier(self, client_with_mock_service):
        """Test validation when identifier is missing."""
        response = client_with_mock_service.post(
            "/api/v1/rate-limit/check", json={"max_requests": 10, "window_seconds": 60}
        )

        assert response.status_code == 422  # Validation error

    def test_reset_rate_limit(self, client_with_mock_service, mock_service):
        """Test reset rate limit endpoint."""
        mock_service.reset_rate_limit = AsyncMock(return_value=True)

        response = client_with_mock_service.post(
            "/api/v1/rate-limit/reset", json={"identifier": "user123", "namespace": "api"}
        )

        assert response.status_code == 204
        mock_service.reset_rate_limit.assert_called_once_with(identifier="user123", namespace="api")

    def test_reset_rate_limit_failure(self, client_with_mock_service, mock_service):
        """Test reset when it fails."""
        mock_service.reset_rate_limit = AsyncMock(return_value=False)

        response = client_with_mock_service.post(
            "/api/v1/rate-limit/reset", json={"identifier": "user123", "namespace": "api"}
        )

        # Should return 500 when reset fails
        assert response.status_code == 500

    def test_get_usage(self, client_with_mock_service, mock_service):
        """Test get usage endpoint."""
        mock_service.get_usage.return_value = {"current_count": 5, "window_start": 1234567890}

        response = client_with_mock_service.get(
            "/api/v1/rate-limit/usage/user123", params={"namespace": "api"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["identifier"] == "user123"
        assert data["namespace"] == "api"
        assert data["current_count"] == 5
        assert data["window_start"] == 1234567890

    def test_health_check(self, client_with_mock_service, mock_service):
        """Test health check endpoint."""
        mock_service.health_check.return_value = True

        response = client_with_mock_service.get("/api/v1/rate-limit/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["redis_healthy"] is True

    def test_health_check_unhealthy(self, client_with_mock_service, mock_service):
        """Test health check when Redis is unhealthy."""
        mock_service.health_check.return_value = False

        response = client_with_mock_service.get("/api/v1/rate-limit/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["redis_healthy"] is False
