"""Unit tests for security.py auth / authz dependencies."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.domain.gateway.models import APIKey, APIKeyRole
from app.presentation.api.security import (
    AUTH_FAILURE_WINDOW_SECONDS,
    MAX_AUTH_FAILURES,
    _auth_failure_key,
    _clear_auth_failures,
    _is_auth_rate_limited,
    _record_auth_failure,
)


def _make_api_key(role: APIKeyRole = APIKeyRole.ADMIN) -> APIKey:
    return APIKey(
        key_id="test",
        key_hash="hash",
        name="Test",
        role=role,
        created_at=datetime(2026, 1, 1),
    )


def _make_redis_wrapper(get_return=None):
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=get_return)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.delete = AsyncMock()
    wrapper = MagicMock()
    wrapper.client = mock_redis
    return wrapper, mock_redis


# ------------------------------------------------------------------ key helper


class TestAuthFailureKey:
    def test_format(self):
        assert _auth_failure_key("1.2.3.4") == "auth_fail:1.2.3.4"


# ------------------------------------------------------------------ _is_auth_rate_limited


class TestIsAuthRateLimited:
    @pytest.mark.asyncio
    async def test_below_threshold_returns_false(self):
        wrapper, mock_redis = _make_redis_wrapper(get_return=str(MAX_AUTH_FAILURES - 1))
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            result = await _is_auth_rate_limited("10.0.0.1")
        assert result is False

    @pytest.mark.asyncio
    async def test_at_threshold_returns_true(self):
        wrapper, mock_redis = _make_redis_wrapper(get_return=str(MAX_AUTH_FAILURES))
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            result = await _is_auth_rate_limited("10.0.0.1")
        assert result is True

    @pytest.mark.asyncio
    async def test_no_key_returns_false(self):
        wrapper, mock_redis = _make_redis_wrapper(get_return=None)
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            result = await _is_auth_rate_limited("10.0.0.1")
        assert result is False

    @pytest.mark.asyncio
    async def test_redis_exception_returns_false(self):
        wrapper = MagicMock()
        wrapper.client.get = AsyncMock(side_effect=Exception("Redis down"))
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            result = await _is_auth_rate_limited("10.0.0.1")
        assert result is False


# ------------------------------------------------------------------ _record_auth_failure


class TestRecordAuthFailure:
    @pytest.mark.asyncio
    async def test_first_failure_sets_expire(self):
        wrapper, mock_redis = _make_redis_wrapper()
        mock_redis.incr.return_value = 1
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            await _record_auth_failure("10.0.0.2")

        mock_redis.incr.assert_called_once_with(_auth_failure_key("10.0.0.2"))
        mock_redis.expire.assert_called_once_with(
            _auth_failure_key("10.0.0.2"), AUTH_FAILURE_WINDOW_SECONDS
        )

    @pytest.mark.asyncio
    async def test_subsequent_failure_does_not_reset_expire(self):
        wrapper, mock_redis = _make_redis_wrapper()
        mock_redis.incr.return_value = 5
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            await _record_auth_failure("10.0.0.2")

        mock_redis.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_exception_is_swallowed(self):
        wrapper = MagicMock()
        wrapper.client.incr = AsyncMock(side_effect=Exception("Redis down"))
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            # Should not raise
            await _record_auth_failure("10.0.0.2")


# ------------------------------------------------------------------ _clear_auth_failures


class TestClearAuthFailures:
    @pytest.mark.asyncio
    async def test_deletes_key(self):
        wrapper, mock_redis = _make_redis_wrapper()
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            await _clear_auth_failures("10.0.0.3")

        mock_redis.delete.assert_called_once_with(_auth_failure_key("10.0.0.3"))

    @pytest.mark.asyncio
    async def test_redis_exception_is_swallowed(self):
        wrapper = MagicMock()
        wrapper.client.delete = AsyncMock(side_effect=Exception("Redis down"))
        with patch(
            "app.presentation.api.security.get_redis_client", return_value=wrapper
        ):
            await _clear_auth_failures("10.0.0.3")


# ------------------------------------------------------------------ verify_api_key full flow


class TestVerifyApiKey:
    def _make_request(self, ip: str = "127.0.0.1"):
        req = MagicMock()
        req.client.host = ip
        return req

    @pytest.mark.asyncio
    async def test_valid_key_clears_failures_and_returns_key(self):
        from app.presentation.api.security import verify_api_key

        api_key = _make_api_key()
        mock_manager = MagicMock()
        mock_manager.validate_key = AsyncMock(return_value=api_key)

        not_limited = MagicMock()
        not_limited.client.get = AsyncMock(return_value=None)
        not_limited.client.delete = AsyncMock()

        with (
            patch("app.presentation.api.security.get_redis_client", return_value=not_limited),
            patch("app.presentation.api.security.get_api_key_manager", return_value=mock_manager),
        ):
            result = await verify_api_key(self._make_request(), "sk_valid")

        assert result == api_key
        not_limited.client.delete.assert_called_once()  # clear failures on success

    @pytest.mark.asyncio
    async def test_invalid_key_records_failure_and_raises_401(self):
        from app.presentation.api.security import verify_api_key

        mock_manager = MagicMock()
        mock_manager.validate_key = AsyncMock(return_value=None)

        wrapper, mock_redis = _make_redis_wrapper(get_return=None)
        mock_redis.incr.return_value = 1

        with (
            patch("app.presentation.api.security.get_redis_client", return_value=wrapper),
            patch("app.presentation.api.security.get_api_key_manager", return_value=mock_manager),
        ):
            with pytest.raises(HTTPException) as exc:
                await verify_api_key(self._make_request(), "sk_bad")

        assert exc.value.status_code == 401
        mock_redis.incr.assert_called_once()  # failure recorded

    @pytest.mark.asyncio
    async def test_rate_limited_ip_raises_429(self):
        from app.presentation.api.security import verify_api_key

        wrapper, mock_redis = _make_redis_wrapper(get_return=str(MAX_AUTH_FAILURES))

        with patch("app.presentation.api.security.get_redis_client", return_value=wrapper):
            with pytest.raises(HTTPException) as exc:
                await verify_api_key(self._make_request(), "sk_any")

        assert exc.value.status_code == 429


# ------------------------------------------------------------------ require_admin / require_user_or_admin


class TestRoleGuards:
    @pytest.mark.asyncio
    async def test_require_admin_allows_admin(self):
        from app.presentation.api.security import require_admin

        key = _make_api_key(APIKeyRole.ADMIN)
        result = await require_admin(key)
        assert result == key

    @pytest.mark.asyncio
    async def test_require_admin_rejects_user(self):
        from app.presentation.api.security import require_admin

        key = _make_api_key(APIKeyRole.USER)
        with pytest.raises(HTTPException) as exc:
            await require_admin(key)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_user_or_admin_allows_admin(self):
        from app.presentation.api.security import require_user_or_admin

        key = _make_api_key(APIKeyRole.ADMIN)
        result = await require_user_or_admin(key)
        assert result == key

    @pytest.mark.asyncio
    async def test_require_user_or_admin_rejects_readonly(self):
        from app.presentation.api.security import require_user_or_admin

        key = _make_api_key(APIKeyRole.READONLY)
        with pytest.raises(HTTPException) as exc:
            await require_user_or_admin(key)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_readonly_or_above_allows_readonly(self):
        from app.presentation.api.security import require_readonly_or_above

        key = _make_api_key(APIKeyRole.READONLY)
        result = await require_readonly_or_above(key)
        assert result == key
