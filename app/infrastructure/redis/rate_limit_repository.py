"""Redis implementation of rate limit repository.

Supported algorithms (configured via RATE_LIMIT_ALGORITHM env var):

  fixed_window
    Counter scoped to a fixed time slot. O(1) memory. Limitation: up to
    2x the limit can pass at a window boundary (N requests at the end of
    window T, then N more at the start of window T+1).

  sliding_window_counter  <- recommended default
    Weighted blend of the current and previous fixed-window counters.
    Approximates a true sliding window with O(1) memory and 2 Redis reads.
    Eliminates the boundary burst while remaining very lightweight.
    Formula: count = prev_count x (1 - elapsed/window) + curr_count

  sliding_window_log
    Stores a timestamp for every request in a Redis sorted set. The window
    is always exactly [now - window_seconds, now]. Perfect accuracy at
    O(N) memory per identifier. Only use when strict accuracy is required
    and per-identifier traffic is low (e.g. billing, auth).

Fail-open behaviour (RATE_LIMIT_FAIL_OPEN):
  True  - allow requests when Redis is unreachable. Maximises availability
          but removes the rate limit guarantee during outages.
          WARNING: do NOT use for billing, fraud prevention, or hard
          tenant-isolation enforcement.
  False - deny requests (HTTP 503) when Redis is unreachable. Maximises
          correctness at the cost of availability during Redis outages.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Literal

from redis.exceptions import RedisError

from app.domain.rate_limit import (
    RateLimitConfig,
    RateLimitRepository,
    RateLimitResult,
    RateLimitStatus,
)
from app.infrastructure.redis.client import RedisClient

Algorithm = Literal["fixed_window", "sliding_window_log", "sliding_window_counter"]


def _throttled(config: RateLimitConfig, retry_after: int, reset_at: datetime) -> RateLimitResult:
    return RateLimitResult(
        status=RateLimitStatus.THROTTLED,
        identifier=config.identifier,
        limit=config.max_requests,
        remaining=0,
        reset_at=reset_at,
        retry_after=retry_after,
    )


def _allowed(config: RateLimitConfig, remaining: int, reset_at: datetime) -> RateLimitResult:
    return RateLimitResult(
        status=RateLimitStatus.ALLOWED,
        identifier=config.identifier,
        limit=config.max_requests,
        remaining=max(0, remaining),
        reset_at=reset_at,
        retry_after=None,
    )


class RedisRateLimitRepository(RateLimitRepository):
    """Redis-backed rate limit repository supporting multiple counting algorithms."""

    def __init__(
        self,
        redis_client: RedisClient,
        key_prefix: str = "rate_limit",
        algorithm: Algorithm = "sliding_window_counter",
        fail_open: bool = True,
    ):
        """
        Args:
            redis_client: Async Redis client wrapper.
            key_prefix:   Namespace prefix for all Redis keys.
            algorithm:    Counting algorithm -- see module docstring.
            fail_open:    Whether to allow requests when Redis is unavailable.
                          Set to False for billing/fraud-prevention use cases.
        """
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._algorithm = algorithm
        self._fail_open = fail_open
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------ helpers

    def _base_key(self, identifier: str, namespace: str) -> str:
        return f"{self._key_prefix}:{namespace}:{identifier}"

    def _fail_result(self, config: RateLimitConfig) -> RateLimitResult:
        """Result to return when Redis is unavailable."""
        reset_at = datetime.now() + timedelta(seconds=config.window_seconds)
        if self._fail_open:
            return _allowed(config, config.max_requests, reset_at)
        return _throttled(config, config.window_seconds, reset_at)

    # ------------------------------------------------------------------ algorithms

    async def _fixed_window(self, rc, config: RateLimitConfig, now: int) -> RateLimitResult:
        """
        Fixed Window Counter.

        Key: {prefix}:{ns}:{id}:{window_start}
        A single integer counter per time slot. Simple and memory-efficient,
        but allows a burst of 2x limit at a window boundary.
        """
        window_start = (now // config.window_seconds) * config.window_seconds
        window_end = window_start + config.window_seconds
        window_key = f"{self._base_key(config.identifier, config.namespace)}:{window_start}"
        reset_at = datetime.fromtimestamp(window_end)

        current = await rc.get(window_key)
        current_count = int(current) if current else 0

        if current_count >= config.max_requests:
            return _throttled(config, window_end - now, reset_at)

        pipe = rc.pipeline()
        pipe.incr(window_key)
        pipe.expire(window_key, config.window_seconds + 10)
        await pipe.execute()

        return _allowed(config, config.max_requests - current_count - 1, reset_at)

    async def _sliding_window_counter(
        self, rc, config: RateLimitConfig, now: int
    ) -> RateLimitResult:
        """
        Sliding Window Counter (weighted approximation).

        Uses two fixed-window buckets (previous + current) and weights the
        previous bucket by how much of the current window has elapsed:

            estimated = prev x (1 - elapsed/window) + curr

        O(1) memory, 2 reads, no boundary burst. Accuracy is within ~0.1%
        of a true sliding window at typical request rates.
        """
        window_seconds = config.window_seconds
        window_start = (now // window_seconds) * window_seconds
        prev_window_start = window_start - window_seconds
        window_end = window_start + window_seconds

        base = self._base_key(config.identifier, config.namespace)
        curr_key = f"{base}:{window_start}"
        prev_key = f"{base}:{prev_window_start}"
        reset_at = datetime.fromtimestamp(window_end)

        curr_raw, prev_raw = await rc.mget(curr_key, prev_key)
        curr_count = int(curr_raw) if curr_raw else 0
        prev_count = int(prev_raw) if prev_raw else 0

        elapsed_in_window = now - window_start
        weight = 1.0 - (elapsed_in_window / window_seconds)
        estimated = int(prev_count * weight) + curr_count

        if estimated >= config.max_requests:
            return _throttled(config, window_end - now, reset_at)

        pipe = rc.pipeline()
        pipe.incr(curr_key)
        pipe.expire(curr_key, window_seconds * 2 + 10)
        await pipe.execute()

        return _allowed(config, config.max_requests - estimated - 1, reset_at)

    async def _sliding_window_log(
        self, rc, config: RateLimitConfig, now: int
    ) -> RateLimitResult:
        """
        Sliding Window Log.

        Stores a sorted set of request timestamps. The window is always
        exactly [now - window_seconds, now]. Accurate to the millisecond
        but memory is O(limit) per identifier.

        Use when perfect accuracy is required and per-identifier request
        volume is bounded (e.g. strict billing controls, auth endpoints).
        """
        window_seconds = config.window_seconds
        cutoff = now - window_seconds
        reset_at = datetime.fromtimestamp(now + window_seconds)
        key = f"{self._base_key(config.identifier, config.namespace)}:log"

        # Atomic: remove expired entries then count
        pipe = rc.pipeline()
        pipe.zremrangebyscore(key, "-inf", cutoff)
        pipe.zcard(key)
        results = await pipe.execute()
        current_count: int = results[1]

        if current_count >= config.max_requests:
            return _throttled(config, window_seconds, reset_at)

        # Use fractional-second score to avoid collisions within the same second
        score = time.time()
        pipe = rc.pipeline()
        pipe.zadd(key, {str(score): score})
        pipe.expire(key, window_seconds + 10)
        await pipe.execute()

        return _allowed(config, config.max_requests - current_count - 1, reset_at)

    # ------------------------------------------------------------------ public interface

    async def check_rate_limit(self, config: RateLimitConfig) -> RateLimitResult:
        """Dispatch to the configured algorithm, with fail-open/fail-closed on Redis error."""
        try:
            rc = self._redis.client
            now = int(time.time())

            if self._algorithm == "fixed_window":
                return await self._fixed_window(rc, config, now)
            elif self._algorithm == "sliding_window_log":
                return await self._sliding_window_log(rc, config, now)
            else:
                return await self._sliding_window_counter(rc, config, now)

        except RedisError as e:
            behaviour = "allowing (fail-open)" if self._fail_open else "denying (fail-closed)"
            self._logger.error(
                "Redis error in rate limit check -- %s request: %s", behaviour, e
            )
            return self._fail_result(config)

    async def reset_rate_limit(self, identifier: str, namespace: str = "default") -> bool:
        """Delete all rate limit keys for an identifier."""
        try:
            rc = self._redis.client
            pattern = f"{self._key_prefix}:{namespace}:{identifier}:*"
            keys = [key async for key in rc.scan_iter(match=pattern)]
            if keys:
                await rc.delete(*keys)
            return True
        except RedisError:
            return False

    async def get_current_usage(
        self, identifier: str, namespace: str = "default"
    ) -> tuple[int, int]:
        """Return (current_count, window_start_timestamp) for the identifier."""
        current_time = int(time.time())
        try:
            rc = self._redis.client
            base = self._base_key(identifier, namespace)

            if self._algorithm == "sliding_window_log":
                key = f"{base}:log"
                count = await rc.zcard(key)
                return (count or 0, current_time)

            # For fixed and sliding counter: find the latest window key
            latest_count, latest_window = 0, current_time
            async for full_key in rc.scan_iter(match=f"{base}:*"):
                count = await rc.get(full_key)
                if count:
                    window_str = full_key.split(":")[-1]
                    latest_count = int(count)
                    latest_window = int(window_str)
                    break

            return (latest_count, latest_window)
        except RedisError:
            return (0, current_time)

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        return await self._redis.health_check()
