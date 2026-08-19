"""Authorized workspace object storage through ZhuoJian Storage Gateway.

The business application never receives an OSS AccessKey.  It asks the
gateway for short-lived, project-scoped signed URLs and stores only an opaque
``oss://`` reference in PostgreSQL.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings

OSS_REF_PREFIX = "oss://"


class StorageGatewayError(RuntimeError):
    """The configured storage gateway could not complete an operation."""


def is_object_ref(value: str | None) -> bool:
    return bool(value and value.startswith(OSS_REF_PREFIX))


def object_key_from_ref(value: str) -> str:
    if not is_object_ref(value):
        raise StorageGatewayError("Invalid workspace object reference")
    key = value[len(OSS_REF_PREFIX):]
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise StorageGatewayError("Unsafe workspace object reference")
    return key


def _auth_headers() -> dict[str, str]:
    token = settings.storage_project_token.strip()
    if not token:
        raise StorageGatewayError("Storage project token is not configured")
    return {"Authorization": f"Bearer {token}"}


def _gateway_url(path: str) -> str:
    base = settings.storage_gateway_url.strip().rstrip("/")
    if not base:
        raise StorageGatewayError("Storage gateway URL is not configured")
    return f"{base}{path}"


def _internal_signed_url(signed_url: str) -> str:
    """Route OSS traffic over the same-region internal endpoint when set.

    Alibaba OSS signed URLs use the object resource and signed headers for
    authentication, so replacing only the endpoint host preserves the
    signature.  Both path-style and bucket-prefixed virtual hosts are handled.
    """
    public = settings.storage_public_endpoint.strip()
    internal = settings.storage_internal_endpoint.strip()
    if not public or not internal:
        return signed_url
    source = urlsplit(signed_url)
    public_host = (urlsplit(public).hostname or "").lower()
    internal_parts = urlsplit(internal)
    internal_host = (internal_parts.hostname or "").lower()
    source_host = (source.hostname or "").lower()
    if not public_host or not internal_host:
        return signed_url
    if source_host == public_host:
        target_host = internal_host
    elif source_host.endswith(f".{public_host}"):
        target_host = f"{source_host[:-(len(public_host) + 1)]}.{internal_host}"
    else:
        return signed_url
    port = f":{internal_parts.port}" if internal_parts.port else ""
    return urlunsplit((
        internal_parts.scheme or source.scheme,
        f"{target_host}{port}",
        source.path,
        source.query,
        source.fragment,
    ))


async def upload_bytes(raw: bytes, *, filename: str, content_type: str) -> str:
    if not raw:
        raise StorageGatewayError("Cannot upload an empty object")
    timeout = settings.storage_gateway_timeout_seconds
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            signed = await client.post(
                _gateway_url("/v1/uploads/sign"),
                headers=_auth_headers(),
                json={"filename": filename, "content_type": content_type, "size_bytes": len(raw)},
            )
            signed.raise_for_status()
            payload = signed.json()
            object_key = str(payload["object_key"])
            upload = await client.put(
                _internal_signed_url(str(payload["url"])),
                headers={str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
                content=raw,
            )
            upload.raise_for_status()
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        # Never include a signed URL (and its signature query) in user-facing
        # errors, logs or database parse_error fields.
        raise StorageGatewayError("OSS upload failed; check storage gateway status") from exc
    return f"{OSS_REF_PREFIX}{object_key}"


async def download_bytes(content_ref: str) -> bytes:
    object_key = object_key_from_ref(content_ref)
    timeout = settings.storage_gateway_timeout_seconds
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            signed = await client.post(
                _gateway_url("/v1/downloads/sign"),
                headers=_auth_headers(),
                json={"object_key": object_key},
            )
            signed.raise_for_status()
            payload = signed.json()
            response = await client.get(_internal_signed_url(str(payload["url"])))
            response.raise_for_status()
            return response.content
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS download failed; check storage gateway status") from exc


async def delete_object(content_ref: str) -> None:
    object_key = object_key_from_ref(content_ref)
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.request(
                "DELETE",
                _gateway_url("/v1/objects"),
                headers=_auth_headers(),
                json={"object_key": object_key},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise StorageGatewayError("OSS delete failed; check storage gateway status") from exc
