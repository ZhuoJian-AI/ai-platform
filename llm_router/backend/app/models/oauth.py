"""OAuth 2.1 records for public MCP clients.

Only hashes of authorization codes and refresh tokens are persisted.  MCP
access tokens are short-lived JWTs whose audience is one organization-specific
protected resource.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class OAuthClient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uris: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    grant_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    response_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    registration_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthAuthorizationCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oauth_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    issued_auth_epoch: Mapped[int] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthRefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oauth_refresh_tokens"
    __table_args__ = (
        Index("ix_oauth_refresh_tokens_family", "family_id"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    family_id: Mapped[UUID] = mapped_column(nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
