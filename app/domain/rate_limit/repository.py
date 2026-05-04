"""Rate limit repository interface."""

from abc import ABC, abstractmethod

from app.domain.rate_limit.models import RateLimitConfig, RateLimitResult


class RateLimitRepository(ABC):
    """Abstract repository for rate limit storage operations."""

    @abstractmethod
    async def check_rate_limit(self, config: RateLimitConfig) -> RateLimitResult:
        """
        Check if a request is within rate limits.
        
        Args:
            config: Rate limit configuration
            
        Returns:
            Result indicating whether the request is allowed
        """
        pass

    @abstractmethod
    async def reset_rate_limit(self, identifier: str, namespace: str = "default") -> bool:
        """
        Reset rate limit for a specific identifier.
        
        Args:
            identifier: Unique identifier (user ID, IP, etc.)
            namespace: Rate limit namespace
            
        Returns:
            True if reset was successful
        """
        pass

    @abstractmethod
    async def get_current_usage(
        self, identifier: str, namespace: str = "default"
    ) -> tuple[int, int]:
        """
        Get current usage for an identifier.
        
        Args:
            identifier: Unique identifier
            namespace: Rate limit namespace
            
        Returns:
            Tuple of (current_count, window_start_timestamp)
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the rate limit storage is healthy.
        
        Returns:
            True if storage is accessible and healthy
        """
        pass
