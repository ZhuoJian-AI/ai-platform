"""OAuth 2.1 authorization-code service for organization-scoped MCP access."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import ParseResult, urlparse
from uuid import UUID, uuid4

import jwt
from fastapi import Request
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.oauth import OAuthAuthorizationCode, OAuthClient, OAuthRefreshToken
from app.models.organization import Organization
from app.models.user import User

MCP_SCOPE = "mcp:tools"


class OAuthProtocolError(ValueError):
    """Safe OAuth error that can be returned to a public client."""

    def __init__(self, error: str, description: str, status_code: int = 400):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _validated_public_origin(request: Request | None = None) -> str:
    configured = settings.normalized_oauth_public_base_url
    if configured:
        parsed = urlparse(configured)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.path not in {"", "/"}:
            raise RuntimeError("OAUTH_PUBLIC_BASE_URL must be an origin without a path")
        if not settings.is_development and parsed.scheme != "https":
            raise RuntimeError("OAUTH_PUBLIC_BASE_URL must use HTTPS outside development")
        return configured
    if settings.is_development and request is not None:
        return str(request.base_url).rstrip("/")
    raise RuntimeError("OAuth public URL is not configured")


def issuer(request: Request | None = None) -> str:
    configured = settings.normalized_oauth_issuer
    value = configured or _validated_public_origin(request)
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise RuntimeError("OAUTH_ISSUER must be an absolute URL")
    if not settings.is_development and parsed.scheme != "https":
        raise RuntimeError("OAUTH_ISSUER must use HTTPS outside development")
    return value.rstrip("/")


def resource_for_org(organization_id: UUID, request: Request | None = None) -> str:
    return f"{_validated_public_origin(request)}/mcp/organizations/{organization_id}"


def parse_resource_org(resource: str, request: Request | None = None) -> UUID:
    """Validate an exact tenant resource URI and return its organization id."""
    expected_origin = urlparse(_validated_public_origin(request))
    parsed = urlparse(resource)
    if parsed.scheme != expected_origin.scheme or parsed.netloc != expected_origin.netloc:
        raise OAuthProtocolError("invalid_target", "resource must use this platform origin")
    if parsed.query or parsed.fragment or parsed.params:
        raise OAuthProtocolError("invalid_target", "resource must not contain query or fragment")
    prefix = "/mcp/organizations/"
    if not parsed.path.startswith(prefix):
        raise OAuthProtocolError("invalid_target", "resource is not an organization MCP endpoint")
    raw_org = parsed.path[len(prefix):].strip("/")
    if "/" in raw_org:
        raise OAuthProtocolError("invalid_target", "resource path is invalid")
    try:
        organization_id = UUID(raw_org)
    except ValueError as exc:
        raise OAuthProtocolError("invalid_target", "resource organization is invalid") from exc
    canonical = resource_for_org(organization_id, request)
    if resource.rstrip("/") != canonical:
        raise OAuthProtocolError("invalid_target", "resource must be canonical")
    return organization_id


def _is_loopback(parsed: ParseResult) -> bool:
    return parsed.hostname in {"127.0.0.1", "::1"}


def validate_redirect_uri(uri: str) -> None:
    parsed = urlparse(uri)
    if parsed.fragment or parsed.username or parsed.password or not parsed.scheme:
        raise OAuthProtocolError("invalid_redirect_uri", "redirect URI is invalid")
    if parsed.scheme == "https" and parsed.netloc:
        return
    if parsed.scheme == "http" and parsed.netloc and _is_loopback(parsed):
        return
    raise OAuthProtocolError(
        "invalid_redirect_uri",
        "redirect URI must use HTTPS or an HTTP loopback literal",
    )


def redirect_uri_matches(registered: str, presented: str) -> bool:
    """Exact match, except that native loopback clients may choose a port."""
    try:
        validate_redirect_uri(registered)
        validate_redirect_uri(presented)
    except OAuthProtocolError:
        return False
    left, right = urlparse(registered), urlparse(presented)
    if left.geturl() == right.geturl():
        return True
    if not (_is_loopback(left) and _is_loopback(right)):
        return False
    return (
        left.scheme == right.scheme == "http"
        and left.hostname == right.hostname
        and left.path == right.path
        and left.params == right.params
        and left.query == right.query
        and left.fragment == right.fragment
    )


def normalize_scope(scope: str | None) -> str:
    requested = set((scope or MCP_SCOPE).split())
    if not requested or not requested.issubset({MCP_SCOPE}):
        raise OAuthProtocolError("invalid_scope", "only mcp:tools is supported")
    return MCP_SCOPE


async def register_public_client(
    db: AsyncSession,
    *,
    client_name: str,
    redirect_uris: list[str],
    registration_source: str,
) -> OAuthClient:
    if not settings.oauth_dynamic_client_registration_enabled:
        raise OAuthProtocolError("registration_not_supported", "dynamic registration is disabled", 403)
    if not client_name.strip() or len(client_name) > 255:
        raise OAuthProtocolError("invalid_client_metadata", "client_name is required")
    if not redirect_uris or len(redirect_uris) > 10 or len(set(redirect_uris)) != len(redirect_uris):
        raise OAuthProtocolError("invalid_redirect_uris", "provide 1 to 10 unique redirect URIs")
    for uri in redirect_uris:
        validate_redirect_uri(uri)
    now = _now()
    source_hash = _hash_secret(registration_source or "unknown")
    # DCR is intentionally public for native MCP clients, but it must not be an
    # unbounded database-write endpoint. Expired clients are removed before
    # applying per-source and global active-client caps.
    await db.execute(delete(OAuthClient).where(OAuthClient.expires_at <= now))
    recent_count = await db.scalar(
        select(func.count(OAuthClient.id)).where(
            OAuthClient.registration_source_hash == source_hash,
            OAuthClient.created_at >= now - timedelta(hours=1),
        )
    )
    if int(recent_count or 0) >= settings.oauth_dynamic_client_limit_per_hour:
        raise OAuthProtocolError("temporarily_unavailable", "client registration rate limit exceeded", 429)
    active_count = await db.scalar(
        select(func.count(OAuthClient.id)).where(
            OAuthClient.is_active.is_(True),
            or_(OAuthClient.expires_at.is_(None), OAuthClient.expires_at > now),
        )
    )
    if int(active_count or 0) >= settings.oauth_dynamic_client_max_active:
        raise OAuthProtocolError("temporarily_unavailable", "client registration capacity reached", 503)
    client = OAuthClient(
        client_id=f"mcp_{secrets.token_urlsafe(32)}",
        client_name=client_name.strip(),
        redirect_uris=redirect_uris,
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        registration_source_hash=source_hash,
        is_active=True,
        expires_at=now + timedelta(days=settings.oauth_dynamic_client_ttl_days),
    )
    db.add(client)
    await db.flush()
    return client


async def get_public_client(db: AsyncSession, client_id: str) -> OAuthClient:
    client = (await db.execute(
        select(OAuthClient).where(OAuthClient.client_id == client_id, OAuthClient.is_active.is_(True))
    )).scalar_one_or_none()
    if client is None or (client.expires_at and client.expires_at <= _now()):
        raise OAuthProtocolError("invalid_client", "unknown or inactive client", 401)
    return client


async def validate_authorization_request(
    db: AsyncSession,
    *,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    scope: str | None,
    request: Request | None = None,
) -> tuple[OAuthClient, UUID, str]:
    if response_type != "code":
        raise OAuthProtocolError("unsupported_response_type", "response_type must be code")
    if code_challenge_method != "S256" or len(code_challenge) < 43:
        raise OAuthProtocolError("invalid_request", "PKCE S256 is required")
    client = await get_public_client(db, client_id)
    if not any(redirect_uri_matches(uri, redirect_uri) for uri in client.redirect_uris):
        raise OAuthProtocolError("invalid_request", "redirect_uri is not registered")
    organization_id = parse_resource_org(resource, request)
    return client, organization_id, normalize_scope(scope)


async def issue_authorization_code(
    db: AsyncSession,
    *,
    client_id: str,
    redirect_uri: str,
    user: User,
    resource: str,
    scope: str,
    code_challenge: str,
) -> str:
    raw = secrets.token_urlsafe(48)
    db.add(OAuthAuthorizationCode(
        code_hash=_hash_secret(raw),
        client_id=client_id,
        redirect_uri=redirect_uri,
        user_id=user.id,
        organization_id=user.organization_id,
        resource=resource,
        scope=scope,
        code_challenge=code_challenge,
        issued_auth_epoch=user.auth_epoch,
        expires_at=_now() + timedelta(seconds=settings.oauth_authorization_code_seconds),
    ))
    await db.flush()
    return raw


def _mint_access_token(
    *,
    user: User,
    client_id: str,
    resource: str,
    scope: str,
    request: Request | None = None,
) -> tuple[str, int]:
    key = settings.oauth_signing_key_value
    if not key:
        raise RuntimeError("OAUTH_SIGNING_KEY is required outside development")
    now = _now()
    seconds = max(60, settings.oauth_access_token_minutes * 60)
    claims = {
        "iss": issuer(request),
        "sub": str(user.id),
        "aud": resource,
        "org": str(user.organization_id),
        "client_id": client_id,
        "scope": scope,
        "auth_epoch": user.auth_epoch,
        "typ": "mcp_access",
        "jti": str(uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=seconds),
    }
    return jwt.encode(claims, key, algorithm="HS256"), seconds


async def _mint_refresh_token(
    db: AsyncSession,
    *,
    user: User,
    client_id: str,
    resource: str,
    scope: str,
    family_id: UUID | None = None,
    absolute_expires_at: datetime | None = None,
) -> tuple[str, OAuthRefreshToken]:
    now = _now()
    raw = secrets.token_urlsafe(64)
    absolute = absolute_expires_at or now + timedelta(days=settings.oauth_refresh_token_absolute_days)
    record = OAuthRefreshToken(
        token_hash=_hash_secret(raw),
        family_id=family_id or uuid4(),
        client_id=client_id,
        user_id=user.id,
        organization_id=user.organization_id,
        resource=resource,
        scope=scope,
        expires_at=min(now + timedelta(days=settings.oauth_refresh_token_days), absolute),
        absolute_expires_at=absolute,
    )
    db.add(record)
    await db.flush()
    return raw, record


async def exchange_authorization_code(
    db: AsyncSession,
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    resource: str,
    request: Request | None = None,
) -> TokenPair:
    await get_public_client(db, client_id)
    record = (await db.execute(
        select(OAuthAuthorizationCode)
        .where(OAuthAuthorizationCode.code_hash == _hash_secret(code))
        .with_for_update()
    )).scalar_one_or_none()
    if record is None or record.consumed_at is not None or record.expires_at <= _now():
        raise OAuthProtocolError("invalid_grant", "authorization code is invalid or expired")
    if (
        record.client_id != client_id
        or record.redirect_uri != redirect_uri
        or record.resource != resource
        or not hmac.compare_digest(record.code_challenge, _b64url_sha256(code_verifier))
    ):
        raise OAuthProtocolError("invalid_grant", "authorization code binding failed")
    parse_resource_org(resource, request)
    user = await db.get(User, record.user_id)
    organization = await db.get(Organization, record.organization_id)
    if (
        user is None
        or organization is None
        or organization.deleted_at is not None
        or not user.is_active
        or user.deleted_at is not None
        or user.organization_id != record.organization_id
        or user.must_change_password
        or user.auth_epoch != record.issued_auth_epoch
    ):
        raise OAuthProtocolError("invalid_grant", "user authorization is no longer active")
    record.consumed_at = _now()
    access, expires_in = _mint_access_token(
        user=user, client_id=client_id, resource=resource, scope=record.scope, request=request,
    )
    refresh, _ = await _mint_refresh_token(
        db, user=user, client_id=client_id, resource=resource, scope=record.scope,
    )
    await db.flush()
    return TokenPair(access, refresh, expires_in, record.scope)


async def rotate_refresh_token(
    db: AsyncSession,
    *,
    refresh_token: str,
    client_id: str,
    resource: str,
    scope: str | None,
    request: Request | None = None,
) -> TokenPair:
    await get_public_client(db, client_id)
    record = (await db.execute(
        select(OAuthRefreshToken)
        .where(OAuthRefreshToken.token_hash == _hash_secret(refresh_token))
        .with_for_update()
    )).scalar_one_or_none()
    now = _now()
    if record is None:
        raise OAuthProtocolError("invalid_grant", "refresh token is invalid")
    if record.used_at is not None or record.revoked_at is not None:
        # Replay of any rotated token invalidates the whole family.
        await db.execute(
            update(OAuthRefreshToken)
            .where(OAuthRefreshToken.family_id == record.family_id)
            .values(revoked_at=now)
        )
        raise OAuthProtocolError("invalid_grant", "refresh token replay detected")
    if record.expires_at <= now or record.absolute_expires_at <= now:
        record.revoked_at = now
        raise OAuthProtocolError("invalid_grant", "refresh token is expired")
    if record.client_id != client_id or record.resource != resource:
        raise OAuthProtocolError("invalid_grant", "refresh token binding failed")
    requested_scope = normalize_scope(scope or record.scope)
    if not set(requested_scope.split()).issubset(set(record.scope.split())):
        raise OAuthProtocolError("invalid_scope", "scope cannot be expanded during refresh")
    parse_resource_org(resource, request)
    user = await db.get(User, record.user_id)
    organization = await db.get(Organization, record.organization_id)
    if (
        user is None
        or organization is None
        or organization.deleted_at is not None
        or not user.is_active
        or user.deleted_at is not None
        or user.organization_id != record.organization_id
    ):
        record.revoked_at = now
        raise OAuthProtocolError("invalid_grant", "user authorization is no longer active")
    raw_next, next_record = await _mint_refresh_token(
        db,
        user=user,
        client_id=client_id,
        resource=resource,
        scope=requested_scope,
        family_id=record.family_id,
        absolute_expires_at=record.absolute_expires_at,
    )
    record.used_at = now
    record.replaced_by_hash = next_record.token_hash
    access, expires_in = _mint_access_token(
        user=user, client_id=client_id, resource=resource, scope=requested_scope, request=request,
    )
    await db.flush()
    return TokenPair(access, raw_next, expires_in, requested_scope)


async def revoke_user_refresh_tokens(db: AsyncSession, user_id: UUID) -> None:
    """Revoke every outstanding OAuth grant owned by a user."""
    now = _now()
    await db.execute(
        update(OAuthRefreshToken)
        .where(OAuthRefreshToken.user_id == user_id, OAuthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.execute(
        update(OAuthAuthorizationCode)
        .where(
            OAuthAuthorizationCode.user_id == user_id,
            OAuthAuthorizationCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )


def decode_mcp_access_token(
    token: str,
    *,
    expected_resource: str,
    request: Request | None = None,
) -> dict:
    key = settings.oauth_signing_key_value
    if not key:
        raise OAuthProtocolError("invalid_token", "OAuth signing key is unavailable", 401)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            audience=expected_resource,
            issuer=issuer(request),
            options={"require": ["exp", "iat", "nbf", "iss", "sub", "aud", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise OAuthProtocolError("invalid_token", "access token is invalid or expired", 401) from exc
    if claims.get("typ") != "mcp_access" or MCP_SCOPE not in str(claims.get("scope", "")).split():
        raise OAuthProtocolError("insufficient_scope", "mcp:tools scope is required", 403)
    return claims
