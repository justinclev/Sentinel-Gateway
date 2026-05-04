"""Redis implementation of rate limit repository."""

import logging
import time
from datetime import datetime, timedelta

from redis.exceptions import RedisError

from app.domain.rate_limit import (
    RateLimitConfig,
    RateLimitRepository,
    RateLimitResult,
    RateLimitStatus,
)
from app.infrastructure.redis.client import RedisClient


class RedisRateLimitRepository(RateLimitRepository):
    """Redis-based rate limit repository using Fixed Window Counter algorithm."""

    def __init__(self, redis_client: RedisClient, key_prefix: str = "rate_limit"):
        """
        Initialize Redis rate limit repository.

        Args:
            redis_client: Redis client instance
            key_prefix: Prefix for Redis keys
        """
        self._redis_client = redis_client
        self._key_prefix = key_prefix
        self._logger = logging.getLogger(__name__)

    def _get_key(self, identifier: str, namespace: str) -> str:
        """Generate Redis key for rate limit."""
        return f"{self._key_prefix}:{namespace}:{identifier}"

    async def check_rate_limit(self, config: RateLimitConfig) -> RateLimitResult:
        """
        Check rate limit using Fixed Window Counter algorithm.

        How it works:
        1. Calculate current window (e.g., if window is 60s, round time to nearest minute)
        2. Get count for this window from Redis
        3. If count < limit: allow and increment
        4. If count >= limit: deny
        """
        try:
            # Get Redis client
            redis_client = self._redis_client.client

            # Generate unique key for this identifier
            key = self._get_key(config.identifier, config.namespace)

            # Calculate current window start time
            # Example: if window=60s and now=125s, window_start=120s
            current_time = int(time.time())
            window_start = (current_time // config.window_seconds) * config.window_seconds
            window_end = window_start + config.window_seconds

            # Create a key that includes the window (so each window gets fresh count)
            window_key = f"{key}:{window_start}"

            # Get current count for this window
            current_count = await redis_client.get(window_key)
            current_count = int(current_count) if current_count else 0

            # Calculate reset time
            reset_at = datetime.fromtimestamp(window_end)

            # Check if we're over the limit
            if current_count >= config.max_requests:
                # THROTTLED - too many requests
                retry_after = window_end - current_time
                return RateLimitResult(
                    status=RateLimitStatus.THROTTLED,
                    identifier=config.identifier,
                    limit=config.max_requests,
                    remaining=0,
                    reset_at=reset_at,
                    retry_after=retry_after,
                )

            # We're under the limit - increment the counter
            pipe = redis_client.pipeline()
            pipe.incr(window_key)  # Increment by 1
            pipe.expire(
                window_key, config.window_seconds + 10
            )  # Auto-delete after window (+10s buffer)
            await pipe.execute()

            # ALLOWED - request can proceed
            remaining = config.max_requests - current_count - 1
            return RateLimitResult(
                status=RateLimitStatus.ALLOWED,
                identifier=config.identifier,
                limit=config.max_requests,
                remaining=remaining,
                reset_at=reset_at,
                retry_after=None,
            )

        except RedisError as e:
            # If Redis fails, log error but allow request (fail open)
            self._logger.error(f"Redis error in rate limit check: {e}")
            return RateLimitResult(
                status=RateLimitStatus.ALLOWED,
                identifier=config.identifier,
                limit=config.max_requests,
                remaining=config.max_requests,
                reset_at=datetime.now() + timedelta(seconds=config.window_seconds),
                retry_after=None,
            )

    async def reset_rate_limit(self, identifier: str, namespace: str = "default") -> bool:
        """Reset rate limit for identifier - deletes their counter."""
        try:
            key_pattern = f"{self._key_prefix}:{namespace}:{identifier}:*"
            redis_client = self._redis_client.client

            # Find all keys for this identifier
            keys = []
            async for key in redis_client.scan_iter(match=key_pattern):
                keys.append(key)

            # Delete them all
            if keys:
                await redis_client.delete(*keys)

            return True
        except RedisError:
            return False

    async def get_current_usage(
        self, identifier: str, namespace: str = "default"
    ) -> tuple[int, int]:
        """Get current usage count and window start."""
        try:
            redis_client = self._redis_client.client
            key = self._get_key(identifier, namespace)

            # Find the current window key
            current_time = int(time.time())
            # We don't know window_seconds here, so we just look for the latest key
            key_pattern = f"{key}:*"

            latest_count = 0
            latest_window = current_time

            async for full_key in redis_client.scan_iter(match=key_pattern):
                count = await redis_client.get(full_key)
                if count:
                    # Extract window timestamp from key
                    window_str = full_key.split(":")[-1]
                    latest_count = int(count)
                    latest_window = int(window_str)
                    break

            return (latest_count, latest_window)
        except RedisError:
            return (0, current_time)

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        return await self._redis_client.health_check()
