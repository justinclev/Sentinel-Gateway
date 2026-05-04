"""Admin API routes for API key management."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.domain.gateway.models import APIKeyRole
from app.infrastructure.security.api_keys import APIKeyManager, get_api_key_manager
from app.presentation.api.security import AdminKey

router = APIRouter()


# ------------------------------------------------------------------ dependencies


def get_manager() -> APIKeyManager:
    """FastAPI dependency for APIKeyManager."""
    return get_api_key_manager()


ManagerDep = Annotated[APIKeyManager, Depends(get_manager)]


# ------------------------------------------------------------------ request / response models


class CreateKeyRequest(BaseModel):
    """Request body for creating a new API key."""

    name: str = Field(..., min_length=1, max_length=200, description="Human-readable key name")
    role: APIKeyRole = Field(..., description="Role assigned to this key")
    expires_at: datetime | None = Field(None, description="Optional expiry timestamp (UTC)")
    rate_limit: int | None = Field(
        None, gt=0, le=1_000_000, description="Optional per-key request cap"
    )
    metadata: dict = Field(default_factory=dict, description="Arbitrary metadata")


class CreateKeyResponse(BaseModel):
    """Response after creating a key. The plain key is returned exactly once."""

    key: str = Field(..., description="Plain API key — store this, it will NOT be shown again")
    key_id: str
    name: str
    role: str
    created_at: str
    expires_at: str | None
    rate_limit: int | None


class KeySummary(BaseModel):
    """Public key metadata — never includes the plain key or hash."""

    key_id: str
    name: str
    role: str
    created_at: str
    expires_at: str | None
    is_active: bool
    rate_limit: int | None
    metadata: dict


# ------------------------------------------------------------------ routes


@router.post(
    "",
    response_model=CreateKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key",
)
async def create_key(
    body: CreateKeyRequest,
    manager: ManagerDep,
    _auth: AdminKey,
) -> CreateKeyResponse:
    """
    Create a new API key.

    **Authentication Required**: ADMIN role only.

    The plain key is returned in this response **exactly once** — it is never
    stored and cannot be retrieved later.
    """
    plain_key, api_key = await manager.create_key(
        name=body.name,
        role=body.role,
        expires_at=body.expires_at,
        rate_limit=body.rate_limit,
        metadata=body.metadata,
    )
    return CreateKeyResponse(
        key=plain_key,
        key_id=api_key.key_id,
        name=api_key.name,
        role=api_key.role.value,
        created_at=api_key.created_at.isoformat(),
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
        rate_limit=api_key.rate_limit,
    )


@router.get(
    "",
    response_model=list[KeySummary],
    summary="List API keys",
)
async def list_keys(
    manager: ManagerDep,
    _auth: AdminKey,
) -> list[KeySummary]:
    """
    List all API keys (metadata only — no plain keys or hashes).

    **Authentication Required**: ADMIN role only.
    """
    keys = await manager.list_keys()
    return [
        KeySummary(
            key_id=k.key_id,
            name=k.name,
            role=k.role.value,
            created_at=k.created_at.isoformat(),
            expires_at=k.expires_at.isoformat() if k.expires_at else None,
            is_active=k.is_active,
            rate_limit=k.rate_limit,
            metadata=k.metadata or {},
        )
        for k in keys
    ]


@router.get(
    "/{key_id}",
    response_model=KeySummary,
    summary="Get API key by ID",
)
async def get_key(
    key_id: str,
    manager: ManagerDep,
    _auth: AdminKey,
) -> KeySummary:
    """
    Get a single API key by its key_id.

    **Authentication Required**: ADMIN role only.
    """
    api_key = await manager.repository.get_by_id(key_id)
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    return KeySummary(
        key_id=api_key.key_id,
        name=api_key.name,
        role=api_key.role.value,
        created_at=api_key.created_at.isoformat(),
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
        is_active=api_key.is_active,
        rate_limit=api_key.rate_limit,
        metadata=api_key.metadata or {},
    )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke API key",
)
async def revoke_key(
    key_id: str,
    manager: ManagerDep,
    _auth: AdminKey,
) -> None:
    """
    Revoke (deactivate) an API key by its key_id.

    **Authentication Required**: ADMIN role only.

    The key is marked inactive but not deleted, so audit history is preserved.
    """
    revoked = await manager.revoke_by_id(key_id)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
