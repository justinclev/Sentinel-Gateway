"""Service factory for dependency injection and scalability."""

from app.application.rate_limit_service import RateLimitService
from app.domain.rate_limit import RateLimitRepository
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.redis import RedisClient, RedisRateLimitRepository, get_redis_client
from logger import get_logger


class ServiceFactory:
    """
    Factory for creating service instances with proper dependency injection.

    This enables:
    - Easy testing with mocked dependencies
    - Horizontal scaling by creating multiple instances
    - Centralized service configuration
    """

    def __init__(
        self,
        settings: Settings | None = None,
        redis_client: RedisClient | None = None,
        repository: RateLimitRepository | None = None,
    ):
        """
        Initialize service factory.

        Args:
            settings: Application settings (uses default if None)
            redis_client: Redis client instance (creates new if None)
            repository: Rate limit repository (creates new if None)
        """
        self._settings = settings or get_settings()
        self._redis_client = redis_client
        self._repository = repository
        self._logger = get_logger("service_factory")

    async def get_redis_client(self) -> RedisClient:
        """Get or create Redis client instance."""
        if self._redis_client is None:
            self._redis_client = await get_redis_client()
        return self._redis_client

    async def get_repository(self) -> RateLimitRepository:
        """Get or create rate limit repository."""
        if self._repository is None:
            redis_client = await self.get_redis_client()
            self._repository = RedisRateLimitRepository(
                redis_client, key_prefix=self._settings.rate_limit_storage_prefix
            )
        return self._repository

    async def get_rate_limit_service(self) -> RateLimitService:
        """
        Create rate limit service instance.

        Returns:
            Configured RateLimitService instance
        """
        repository = await self.get_repository()
        logger = get_logger("rate_limit_service")
        return RateLimitService(repository, logger)


# Global factory instance (can be overridden for testing)
_service_factory: ServiceFactory | None = None


def get_service_factory() -> ServiceFactory:
    """Get or create global service factory."""
    global _service_factory
    if _service_factory is None:
        _service_factory = ServiceFactory()
    return _service_factory


def set_service_factory(factory: ServiceFactory) -> None:
    """Set global service factory (useful for testing)."""
    global _service_factory
    _service_factory = factory


async def create_rate_limit_service() -> RateLimitService:
    """
    Create a new rate limit service instance.

    This is useful for creating multiple service instances
    for horizontal scaling or isolated processing.
    """
    factory = get_service_factory()
    return await factory.get_rate_limit_service()
