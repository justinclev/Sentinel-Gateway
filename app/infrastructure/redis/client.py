"""Redis client wrapper."""

import logging

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import RedisError


class RedisClient:
    """Async Redis client wrapper."""

    def __init__(self, url: str, max_connections: int = 50):
        """
        Initialize Redis client.

        Args:
            url: Redis connection URL
            max_connections: Maximum number of connections in pool
        """
        self._url = url
        self._max_connections = max_connections
        self._pool: redis.ConnectionPool | None = None
        self._client: Redis | None = None
        self._logger = logging.getLogger(__name__)

    async def connect(self) -> None:
        """Establish Redis connection."""
        try:
            # Create a connection pool (reusable connections for efficiency)
            self._pool = redis.ConnectionPool.from_url(
                self._url,
                max_connections=self._max_connections,
                decode_responses=True,  # Makes responses human-readable strings
            )

            # Create the actual client
            self._client = redis.Redis(connection_pool=self._pool)

            # Test the connection with a PING
            await self._client.ping()
            self._logger.info("Successfully connected to Redis")

        except RedisError as e:
            self._logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._logger.info("Disconnected from Redis")
        if self._pool:
            await self._pool.aclose()

    async def health_check(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            if self._client:
                await self._client.ping()
                return True
            return False
        except RedisError:
            return False

    @property
    def client(self) -> Redis:
        """Get Redis client instance."""
        # TODO: Return actual Redis client once connected
        if not self._client:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client


# Global Redis client instance
_redis_client: RedisClient | None = None


async def get_redis_client() -> RedisClient:
    """Get or create global Redis client instance."""
    global _redis_client
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized")
    return _redis_client


async def initialize_redis(url: str, max_connections: int = 50) -> RedisClient:
    """Initialize global Redis client."""
    global _redis_client
    _redis_client = RedisClient(url, max_connections)
    await _redis_client.connect()
    return _redis_client


async def close_redis() -> None:
    """Close global Redis client."""
    global _redis_client
    if _redis_client:
        await _redis_client.disconnect()
        _redis_client = None
