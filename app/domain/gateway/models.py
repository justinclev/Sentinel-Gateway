"""API Key domain models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class APIKeyRole(StrEnum):
    """API Key roles for authorization."""

    ADMIN = "admin"  # Full access including reset, usage stats
    USER = "user"  # Rate limit checks only
    READONLY = "readonly"  # Health checks and usage stats only


@dataclass
class APIKey:
    """API Key domain model."""

    key_id: str
    key_hash: str  # SHA-256 hash — never store plain keys
    name: str
    role: APIKeyRole
    created_at: datetime
    expires_at: datetime | None = None
    is_active: bool = True
    rate_limit: int | None = None  # Optional per-key override
    metadata: dict = field(default_factory=dict)
