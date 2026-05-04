"""Basic smoke tests - these should work even without implementation."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_root_endpoint() -> None:
    """Test root endpoint is accessible."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data


def test_health_endpoint() -> None:
    """Test health endpoint is accessible."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


# TODO: Add tests for your rate limiting implementation
# def test_rate_limit_check():
#     response = client.post("/api/v1/rate-limit/check", json={...})
#     assert response.status_code == 200
