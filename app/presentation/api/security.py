"""Security dependencies for API authentication and authorization."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.infrastructure.security import APIKey, APIKeyRole, get_api_key_manager


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
    api_key_str: Annotated[str, Depends(get_api_key_from_header)],
) -> APIKey:
    """
    Verify API key is valid.

    Args:
        api_key_str: API key from header

    Returns:
        APIKey object if valid

    Raises:
        HTTPException: If key is invalid or expired
    """
    manager = get_api_key_manager()
    validated_key = await manager.validate_key(api_key_str)

    if not validated_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

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
    """Require user or admin role."""
    if api_key.role not in [APIKeyRole.USER, APIKeyRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User or admin access required",
        )
    return api_key


# Type aliases for dependencies
AuthenticatedKey = Annotated[APIKey, Depends(verify_api_key)]
AdminKey = Annotated[APIKey, Depends(require_admin)]
UserKey = Annotated[APIKey, Depends(require_user_or_admin)]
