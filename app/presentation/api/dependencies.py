"""FastAPI dependency injection."""

from typing import Annotated

from fastapi import Depends

from app.application.rate_limit_service import RateLimitService
from app.application.service_factory import get_service_factory
from app.infrastructure.config import Settings, get_settings


async def get_rate_limit_service() -> RateLimitService:
    """
    Dependency for rate limit service.

    Uses service factory for proper dependency injection and scalability.

    Returns:
        Configured rate limit service instance
    """
    factory = get_service_factory()
    return await factory.get_rate_limit_service()


# Type aliases for dependency injection
SettingsDep = Annotated[Settings, Depends(get_settings)]
RateLimitServiceDep = Annotated[RateLimitService, Depends(get_rate_limit_service)]
