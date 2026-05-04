"""API route handlers."""

import re

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.presentation.api.dependencies import RateLimitServiceDep
from app.presentation.api.security import AdminKey, AuthenticatedKey, UserKey

# API Router
router = APIRouter()

# Identifier validation pattern (alphanumeric, hyphens, underscores, dots)
IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{1,255}$")


def validate_identifier(identifier: str) -> str:
    """
    Validate identifier to prevent injection attacks.

    Args:
        identifier: User-provided identifier

    Returns:
        Validated identifier

    Raises:
        ValueError: If identifier is invalid
    """
    if not IDENTIFIER_PATTERN.match(identifier):
        raise ValueError(
            "Identifier must be 1-255 alphanumeric characters, hyphens, underscores, or dots"
        )
    return identifier


# Request/Response Models
class RateLimitCheckRequest(BaseModel):
    """Request model for rate limit check."""

    identifier: str = Field(..., description="Unique identifier (user ID, IP, API key, etc.)")
    max_requests: int = Field(..., gt=0, le=1000000, description="Maximum requests allowed")
    window_seconds: int = Field(..., gt=0, le=86400, description="Time window in seconds")
    namespace: str = Field(default="default", description="Rate limit namespace")

    @field_validator("identifier")
    @classmethod
    def validate_identifier_field(cls, v: str) -> str:
        """Validate identifier field."""
        return validate_identifier(v)

    @field_validator("namespace")
    @classmethod
    def validate_namespace_field(cls, v: str) -> str:
        """Validate namespace field."""
        return validate_identifier(v)


class RateLimitCheckResponse(BaseModel):
    """Response model for rate limit check."""

    allowed: bool = Field(..., description="Whether the request is allowed")
    status: str = Field(..., description="Rate limit status")
    identifier: str = Field(..., description="Identifier that was checked")
    limit: int = Field(..., description="Maximum requests allowed")
    remaining: int = Field(..., description="Remaining requests in window")
    reset_at: str = Field(..., description="Timestamp when the limit resets")
    retry_after: int | None = Field(None, description="Seconds to wait before retrying")


class RateLimitResetRequest(BaseModel):
    """Request model for rate limit reset."""

    identifier: str = Field(..., description="Identifier to reset")
    namespace: str = Field(default="default", description="Rate limit namespace")

    @field_validator("identifier")
    @classmethod
    def validate_identifier_field(cls, v: str) -> str:
        """Validate identifier field."""
        return validate_identifier(v)

    @field_validator("namespace")
    @classmethod
    def validate_namespace_field(cls, v: str) -> str:
        """Validate namespace field."""
        return validate_identifier(v)


class UsageResponse(BaseModel):
    """Response model for usage statistics."""

    identifier: str = Field(..., description="Identifier")
    namespace: str = Field(..., description="Namespace")
    current_count: int = Field(..., description="Current request count")
    window_start: int = Field(..., description="Window start timestamp")


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str = Field(..., description="Service health status")
    redis_healthy: bool = Field(..., description="Redis connection status")


# Routes
@router.post("/check", response_model=RateLimitCheckResponse, status_code=status.HTTP_200_OK)
async def check_rate_limit(
    request: RateLimitCheckRequest,
    service: RateLimitServiceDep,
    api_key: UserKey,  # Requires USER or ADMIN role
) -> RateLimitCheckResponse:
    """
    Check if a request is within rate limits.

    **Authentication Required**: USER or ADMIN role

    Args:
        request: Rate limit check parameters
        service: Rate limit service
        api_key: Authenticated API key

    Returns:
        Rate limit check result
    """
    result = await service.check_rate_limit(
        identifier=request.identifier,
        max_requests=request.max_requests,
        window_seconds=request.window_seconds,
        namespace=request.namespace,
    )

    return RateLimitCheckResponse(
        allowed=result.is_allowed,
        status=result.status.value,
        identifier=result.identifier,
        limit=result.limit,
        remaining=result.remaining,
        reset_at=result.reset_at.isoformat(),
        retry_after=result.retry_after,
    )


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_rate_limit(
    request: RateLimitResetRequest,
    service: RateLimitServiceDep,
    api_key: AdminKey,  # Requires ADMIN role
) -> None:
    """
    Reset rate limit for a specific identifier.

    **Authentication Required**: ADMIN role only

    Args:
        request: Reset request parameters
        service: Rate limit service
        api_key: Authenticated admin API key

    Returns:
        None
    """
    success = await service.reset_rate_limit(
        identifier=request.identifier,
        namespace=request.namespace,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset rate limit",
        )


@router.get("/usage/{identifier}", response_model=UsageResponse)
async def get_usage(
    identifier: str,
    service: RateLimitServiceDep,
    api_key: AuthenticatedKey,  # Any authenticated key
    namespace: str = "default",
) -> UsageResponse:
    """
    Get current usage statistics for an identifier.

    **Authentication Required**: Any valid API key

    Args:
        identifier: Unique identifier
        service: Rate limit service
        api_key: Authenticated API key
        namespace: Rate limit namespace

    Returns:
        Usage statistics
    """
    # Validate identifier
    identifier = validate_identifier(identifier)
    namespace = validate_identifier(namespace)

    usage = await service.get_usage(identifier, namespace)

    return UsageResponse(
        identifier=identifier,
        namespace=namespace,
        current_count=usage["current_count"],
        window_start=usage["window_start"],
    )


@router.get("/health", response_model=HealthResponse)
async def health_check(
    service: RateLimitServiceDep,
    api_key: AuthenticatedKey,  # Any authenticated key
) -> HealthResponse:
    """
    Health check endpoint.

    **Authentication Required**: Any valid API key

    Args:
        service: Rate limit service
        api_key: Authenticated API key

    Returns:
        Health status
    """
    redis_healthy = await service.health_check()

    return HealthResponse(
        status="healthy" if redis_healthy else "degraded",
        redis_healthy=redis_healthy,
    )
