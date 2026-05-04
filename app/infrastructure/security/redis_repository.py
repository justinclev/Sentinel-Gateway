"""Redis-backed API key repository."""

import json
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from redis.asyncio import Redis

if TYPE_CHECKING:
    from app.infrastructure.security.api_keys import APIKey, APIKeyRole


class RedisAPIKeyRepository:
    """Repository for API key storage in Redis."""

    KEY_PREFIX = "apikey"
    TTL_DAYS = 365  # Default TTL for keys (1 year)

    def __init__(self, redis_client: Redis):
        """
        Initialize repository with Redis client.

        Args:
            redis_client: Redis async client
        """
        self.redis = redis_client

    def _make_key(self, key_hash: str) -> str:
        """Create Redis key from hash."""
        return f"{self.KEY_PREFIX}:{key_hash}"

    async def get_by_hash(self, key_hash: str) -> Optional["APIKey"]:
        """
        Get API key by hash.

        Args:
            key_hash: SHA-256 hash of the key

        Returns:
            APIKey if found, None otherwise
        """
        # Import here to avoid circular import
        from app.infrastructure.security.api_keys import APIKey, APIKeyRole

        redis_key = self._make_key(key_hash)
        data = await self.redis.get(redis_key)

        if not data:
            return None

        # Parse JSON data
        key_data = json.loads(data)

        # Convert to domain object
        return APIKey(
            key_id=key_data["key_id"],
            key_hash=key_hash,
            name=key_data["name"],
            role=APIKeyRole(key_data["role"]),
            created_at=datetime.fromisoformat(key_data["created_at"]),
            expires_at=(
                datetime.fromisoformat(key_data["expires_at"])
                if key_data.get("expires_at")
                else None
            ),
            is_active=key_data["is_active"],
            rate_limit=key_data.get("rate_limit"),
            metadata=key_data.get("metadata", {}),
        )

    async def create(self, api_key: "APIKey", ttl_seconds: Optional[int] = None) -> "APIKey":
        """
        Create new API key in Redis.

        Args:
            api_key: APIKey domain object
            ttl_seconds: Optional TTL in seconds (default: 1 year)

        Returns:
            Created APIKey
        """
        redis_key = self._make_key(api_key.key_hash)

        # Serialize to JSON
        key_data = {
            "key_id": api_key.key_id,
            "name": api_key.name,
            "role": api_key.role.value,
            "created_at": api_key.created_at.isoformat(),
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            "is_active": api_key.is_active,
            "rate_limit": api_key.rate_limit,
            "metadata": api_key.metadata or {},
        }

        # Store in Redis with TTL
        ttl = ttl_seconds or (self.TTL_DAYS * 86400)
        await self.redis.setex(redis_key, ttl, json.dumps(key_data))

        return api_key

    async def update(self, api_key: "APIKey") -> "APIKey":
        """
        Update existing API key.

        Args:
            api_key: APIKey domain object

        Returns:
            Updated APIKey
        """
        # For Redis, update is the same as create (overwrites)
        # Get existing TTL to preserve it
        redis_key = self._make_key(api_key.key_hash)
        ttl = await self.redis.ttl(redis_key)

        # If key doesn't exist or has no TTL, use default
        if ttl <= 0:
            ttl = self.TTL_DAYS * 86400

        return await self.create(api_key, ttl_seconds=ttl)

    async def delete(self, key_hash: str) -> bool:
        """
        Delete API key.

        Args:
            key_hash: Key hash to delete

        Returns:
            True if deleted, False if not found
        """
        redis_key = self._make_key(key_hash)
        result = await self.redis.delete(redis_key)
        return result > 0

    async def list_all(self) -> list["APIKey"]:
        """
        List all API keys.

        Note: This scans Redis and should be used sparingly.

        Returns:
            List of APIKey objects
        """
        # Import here to avoid circular import
        from app.infrastructure.security.api_keys import APIKey, APIKeyRole

        keys = []
        pattern = f"{self.KEY_PREFIX}:*"

        # Scan for all API keys
        async for key in self.redis.scan_iter(match=pattern, count=100):
            data = await self.redis.get(key)
            if data:
                key_data = json.loads(data)
                # Extract hash from Redis key (key is already a str due to decode_responses=True)
                key_hash = key.split(":", 1)[1]
                keys.append(
                    APIKey(
                        key_id=key_data["key_id"],
                        key_hash=key_hash,
                        name=key_data["name"],
                        role=APIKeyRole(key_data["role"]),
                        created_at=datetime.fromisoformat(key_data["created_at"]),
                        expires_at=(
                            datetime.fromisoformat(key_data["expires_at"])
                            if key_data.get("expires_at")
                            else None
                        ),
                        is_active=key_data["is_active"],
                        rate_limit=key_data.get("rate_limit"),
                        metadata=key_data.get("metadata", {}),
                    )
                )

        return keys
