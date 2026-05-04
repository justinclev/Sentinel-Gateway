"""Rate limit domain models."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RateLimitStatus(StrEnum):
    """Status of a rate limit check."""

    ALLOWED = "allowed"
    THROTTLED = "throttled"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RateLimitConfig:
    """Configuration for a rate limit rule."""

    identifier: str  # User ID, IP address, API key, etc.
    max_requests: int  # Maximum number of requests
    window_seconds: int  # Time window in seconds
    namespace: str = "default"  # Rate limit namespace/category

    def __post_init__(self) -> None:
        """Validate rate limit configuration."""
        if self.max_requests <= 0:
            raise ValueError("max_requests must be greater than 0")

        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be greater than 0")

        if not self.identifier:
            raise ValueError("identifier cannot be empty")


@dataclass(frozen=True)
class RateLimitResult:
    """Result of a rate limit check."""

    status: RateLimitStatus
    identifier: str
    limit: int
    remaining: int
    reset_at: datetime
    retry_after: int | None = None

    @property
    def is_allowed(self) -> bool:
        """Check if the request is allowed."""
        return self.status == RateLimitStatus.ALLOWED

    @property
    def is_throttled(self) -> bool:
        """Check if the request is throttled."""
        return self.status == RateLimitStatus.THROTTLED
