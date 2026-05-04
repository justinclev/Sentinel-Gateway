"""API Key authentication and management."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.infrastructure.security.redis_repository import RedisAPIKeyRepository


class APIKeyRole(str, Enum):
    """API Key roles for authorization."""

    ADMIN = "admin"  # Full access including reset, usage stats
    USER = "user"  # Rate limit checks only
    READONLY = "readonly"  # Health checks and usage stats only


@dataclass
class APIKey:
    """API Key model."""

    key_id: str
    key_hash: str  # Never store plain keys
    name: str
    role: APIKeyRole
    created_at: datetime
    expires_at: datetime | None = None
    is_active: bool = True
    rate_limit: int | None = None  # Optional rate limit for this key
    metadata: dict | None = None


class APIKeyManager:
    """Manages API keys using Redis."""

    def __init__(self, repository: RedisAPIKeyRepository):
        """
        Initialize with Redis repository.

        Args:
            repository: RedisAPIKeyRepository for Redis operations
        """
        self.repository = repository

    @staticmethod
    def _hash_key(key: str) -> str:
        """Hash API key using SHA-256."""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def generate_key(prefix: str = "sk") -> str:
        """Generate a new API key."""
        random_part = secrets.token_urlsafe(32)
        return f"{prefix}_{random_part}"

    async def validate_key(self, key: str) -> APIKey | None:
        """
        Validate API key and return key info if valid.

        Args:
            key: API key to validate

        Returns:
            APIKey object if valid, None otherwise
        """
        key_hash = self._hash_key(key)
        api_key = await self.repository.get_by_hash(key_hash)

        if not api_key:
            return None

        if not api_key.is_active:
            return None

        if api_key.expires_at and datetime.now() > api_key.expires_at:
            return None

        return api_key

    async def create_key(
        self,
        name: str,
        role: APIKeyRole,
        expires_at: datetime | None = None,
        rate_limit: int | None = None,
        metadata: dict | None = None,
    ) -> tuple[str, APIKey]:
        """
        Create a new API key.

        Args:
            name: Key name/description
            role: Key role
            expires_at: Optional expiration datetime
            rate_limit: Optional rate limit for this key
            metadata: Optional metadata

        Returns:
            Tuple of (plain_key, APIKey object)
        """
        plain_key = self.generate_key()
        key_hash = self._hash_key(plain_key)

        api_key = APIKey(
            key_id=f"{role.value}_{secrets.token_hex(4)}",
            key_hash=key_hash,
            name=name,
            role=role,
            created_at=datetime.now(),
            expires_at=expires_at,
            rate_limit=rate_limit,
            metadata=metadata or {},
        )

        created_key = await self.repository.create(api_key)
        return plain_key, created_key

    async def revoke_key(self, key: str) -> bool:
        """
        Revoke an API key.

        Args:
            key: API key to revoke

        Returns:
            True if revoked, False if not found
        """
        key_hash = self._hash_key(key)
        api_key = await self.repository.get_by_hash(key_hash)

        if not api_key:
            return False

        api_key.is_active = False
        await self.repository.update(api_key)
        return True

    async def list_keys(self) -> list[APIKey]:
        """List all API keys."""
        return await self.repository.list_all()


async def initialize_default_keys(repository: RedisAPIKeyRepository) -> None:
    """
    Initialize default API keys for development.
    
    Args:
        repository: Redis repository
    """
    manager = APIKeyManager(repository)
    
    # Check if keys already exist
    existing_keys = await repository.list_all()
    if existing_keys:
        return  # Keys already initialized
    
    # Admin key: sk_admin_dev_12345
    admin_key_plain = "sk_admin_dev_12345"
    admin_key = APIKey(
        key_id="admin_001",
        key_hash=manager._hash_key(admin_key_plain),
        name="Default Admin Key",
        role=APIKeyRole.ADMIN,
        created_at=datetime.now(),
        metadata={"env": "development"},
    )
    await repository.create(admin_key)
    
    # User key: sk_user_dev_67890
    user_key_plain = "sk_user_dev_67890"
    user_key = APIKey(
        key_id="user_001",
        key_hash=manager._hash_key(user_key_plain),
        name="Default User Key",
        role=APIKeyRole.USER,
        created_at=datetime.now(),
        metadata={"env": "development"},
    )
    await repository.create(user_key)


# Global API key manager instance
_api_key_manager: APIKeyManager | None = None


def set_api_key_manager(manager: APIKeyManager) -> None:
    """
    Set the global API key manager instance.
    
    Args:
        manager: APIKeyManager instance to use globally
    """
    global _api_key_manager
    _api_key_manager = manager


def get_api_key_manager() -> APIKeyManager:
    """
    Get the global API key manager instance.
    
    Raises:
        RuntimeError: If manager not initialized
    """
    global _api_key_manager
    if _api_key_manager is None:
        raise RuntimeError(
            "APIKeyManager not initialized. Call set_api_key_manager() in application startup."
        )
    return _api_key_manager
