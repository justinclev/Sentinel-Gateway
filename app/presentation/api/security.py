"""Security dependencies for API authentication and authorization."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.infrastructure.redis.client import get_redis_client
from app.infrastructure.security import APIKey, APIKeyRole, get_api_key_manager

# Auth failure rate limiting: block IP after this many failures within the window
MAX_AUTH_FAILURES = 10
AUTH_FAILURE_WINDOW_SECONDS = 300  # 5 minutes


def _auth_failure_key(ip: str) -> str:
    return f"auth_fail:{ip}"


async def _is_auth_rate_limited(ip: str) -> bool:
    """Return True if the IP has exceeded the auth failure threshold."""
    try:
        wrapper = await get_redis_client()
        count = await wrapper.client.get(_auth_failure_key(ip))
        return int(count) >= MAX_AUTH_FAILURES if count else False
    except Exception:
        return False  # Fail open if Redis unavailable


async def _record_auth_failure(ip: str) -> None:
    """Increment the auth failure counter for an IP, setting TTL on first failure."""
    try:
        wrapper = await get_redis_client()
        key = _auth_failure_key(ip)
        count = await wrapper.client.incr(key)
        if count == 1:
            await wrapper.client.expire(key, AUTH_FAILURE_WINDOW_SECONDS)
    except Exception:
        pass


async def _clear_auth_failures(ip: str) -> None:
    """Clear auth failure counter after a successful authentication."""
    try:
        wrapper = await get_redis_client()
        await wrapper.client.delete(_auth_failure_key(ip))
    except Exception:
        pass


async def get_api_key_from_header(
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """
    Extract API key from headers.

    Supports two formats:
    1. X-API-Key: sk_xxx
    2. Authorization: Bearer sk_xxx
    """
    api_key = x_api_key

    # Try Authorization header if X-API-Key not present
    if not api_key and authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]  # Remove "Bearer " prefix

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide via X-API-Key header or Authorization: Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return api_key


async def verify_api_key(
    request: Request,
    api_key_str: Annotated[str, Depends(get_api_key_from_header)],
) -> APIKey:
    """
    Verify API key is valid, with per-IP brute-force protection.

    Args:
        request: Incoming HTTP request (used for client IP)
        api_key_str: API key from header

    Returns:
        APIKey object if valid

    Raises:
        HTTPException: 429 if IP is rate-limited; 401 if key is invalid
    """
    client_ip = request.client.host if request.client else "unknown"

    if await _is_auth_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed authentication attempts. Try again later.",
            headers={"Retry-After": str(AUTH_FAILURE_WINDOW_SECONDS)},
        )

    manager = get_api_key_manager()
    validated_key = await manager.validate_key(api_key_str)

    if not validated_key:
        await _record_auth_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Successful auth resets the failure counter
    await _clear_auth_failures(client_ip)
    return validated_key


async def require_role(
    required_role: APIKeyRole, api_key: Annotated[APIKey, Depends(verify_api_key)]
) -> APIKey:
    """
    Require specific role for endpoint access.

    Args:
        required_role: Required role
        api_key: Validated API key

    Returns:
        APIKey if authorized

    Raises:
        HTTPException: If insufficient permissions
    """
    # Admin role has access to everything
    if api_key.role == APIKeyRole.ADMIN:
        return api_key

    # Check if role matches
    if api_key.role != required_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required role: {required_role.value}",
        )

    return api_key


async def require_admin(
    api_key: Annotated[APIKey, Depends(verify_api_key)]
) -> APIKey:
    """Require admin role."""
    if api_key.role != APIKeyRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return api_key


async def require_user_or_admin(
    api_key: Annotated[APIKey, Depends(verify_api_key)]
) -> APIKey:
    """Require USER or ADMIN role. READONLY keys are rejected."""
    if api_key.role not in [APIKeyRole.USER, APIKeyRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User or admin access required",
        )
    return api_key


async def require_readonly_or_above(
    api_key: Annotated[APIKey, Depends(verify_api_key)]
) -> APIKey:
    """Require READONLY, USER, or ADMIN role (read-only endpoints)."""
    # All authenticated roles are accepted; READONLY is the minimum privilege
    if api_key.role not in [APIKeyRole.READONLY, APIKeyRole.USER, APIKeyRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return api_key


# Type aliases for dependencies
# AuthenticatedKey  — any valid, active key (no role restriction)
# ReadonlyKey       — READONLY, USER, or ADMIN (GET / read-only endpoints)
# UserKey           — USER or ADMIN (state-mutating endpoints)
# AdminKey          — ADMIN only (administrative endpoints)
AuthenticatedKey = Annotated[APIKey, Depends(verify_api_key)]
ReadonlyKey = Annotated[APIKey, Depends(require_readonly_or_above)]
AdminKey = Annotated[APIKey, Depends(require_admin)]
UserKey = Annotated[APIKey, Depends(require_user_or_admin)]
