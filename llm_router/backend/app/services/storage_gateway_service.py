"""Authorized workspace object storage through ZhuoJian Storage Gateway.

The business application never receives an OSS AccessKey.  It asks the
gateway for short-lived, project-scoped signed URLs and stores only an opaque
``oss://`` reference in PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings

OSS_REF_PREFIX = "oss://"
WORKSPACE_MULTIPART_THRESHOLD_BYTES = 8 * 1024 * 1024
STORAGE_AUTHORIZATION_SUBJECT = "ai-platform-control-plane"


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
    return {
        "Authorization": f"Bearer {token}",
        "X-Storage-Subject": STORAGE_AUTHORIZATION_SUBJECT,
    }


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


async def upload_skill_archive(raw: bytes, *, organization_id: str, package_hash: str) -> str:
    """Store one immutable Skill package through the private project gateway.

    The logical name is deterministic and intentionally contains no original
    user filename. The gateway remains authoritative for the physical object
    key and the database stores only the returned opaque reference.
    """
    if len(package_hash) != 64 or any(ch not in "0123456789abcdef" for ch in package_hash):
        raise StorageGatewayError("Invalid Skill package hash")
    return await upload_bytes(
        raw,
        filename=f"skill-packages/{organization_id}/{package_hash}.zip",
        content_type="application/zip",
    )


async def sign_browser_upload(*, filename: str, content_type: str, size_bytes: int) -> dict:
    """Create a browser upload policy or multipart session without exposing credentials."""
    if size_bytes <= 0 or size_bytes > settings.workspace_max_file_bytes:
        raise StorageGatewayError("Object size is outside the configured workspace limit")
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            path = (
                "/v1/multipart/initiate"
                if size_bytes >= WORKSPACE_MULTIPART_THRESHOLD_BYTES
                else "/v1/uploads/sign"
            )
            response = await client.post(
                _gateway_url(path),
                headers=_auth_headers(),
                json={
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                    **(
                        {"part_size_bytes": 2 * 1024 * 1024, "force_multipart": True}
                        if path == "/v1/multipart/initiate"
                        else {}
                    ),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if path == "/v1/multipart/initiate":
                return {
                    "method": "MULTIPART",
                    "object_key": str(payload["object_key"]),
                    "gateway_session_id": str(payload["session_id"]),
                    "part_size": int(payload["part_size"]),
                    "expected_parts": int(payload["expected_parts"]),
                    "expires_at": str(payload["expires_at"]),
                }
            return {
                "method": "PUT",
                "url": str(payload["url"]),
                "headers": {str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
                "object_key": str(payload["object_key"]),
                "expires_in": int(payload.get("expires_in") or 300),
            }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS upload signing failed; check token limit and CORS") from exc


async def sign_multipart_part(gateway_session_id: str, part_number: int) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.post(
                _gateway_url(f"/v1/multipart/{gateway_session_id}/parts/{part_number}/sign"),
                headers=_auth_headers(),
            )
            response.raise_for_status()
            payload = response.json()
            return {
                "method": "PUT",
                "url": str(payload["url"]),
                "headers": {},
                "part_number": int(payload["part_number"]),
                "expires_in": int(payload.get("expires_in") or 120),
            }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS multipart part signing failed") from exc


async def get_multipart_status(gateway_session_id: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.get(
                _gateway_url(f"/v1/multipart/{gateway_session_id}"), headers=_auth_headers(),
            )
            response.raise_for_status()
            payload = response.json()
            return {
                "status": str(payload["status"]),
                "part_size": int(payload["part_size"]),
                "expected_parts": int(payload["expected_parts"]),
                "uploaded_parts": [
                    {
                        "part_number": int(part["part_number"]),
                        "etag": str(part["etag"]),
                        "size": int(part["size"]),
                    }
                    for part in payload.get("uploaded_parts") or []
                ],
                "expires_at": str(payload["expires_at"]),
            }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS multipart status failed") from exc


async def complete_multipart_upload(gateway_session_id: str, parts: list[dict]) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.post(
                _gateway_url(f"/v1/multipart/{gateway_session_id}/complete"),
                headers=_auth_headers(),
                json={"parts": parts},
            )
            response.raise_for_status()
            payload = response.json()
            return {"status": str(payload["status"]), "etag": str(payload.get("etag") or "")}
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS multipart completion failed") from exc


async def abort_multipart_upload(gateway_session_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.delete(
                _gateway_url(f"/v1/multipart/{gateway_session_id}"), headers=_auth_headers(),
            )
            if response.status_code not in {404, 410}:
                response.raise_for_status()
    except httpx.HTTPError as exc:
        raise StorageGatewayError("OSS multipart abort failed") from exc


async def finalize_policy_upload(object_key: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.post(
                _gateway_url("/v2/uploads/finalize"),
                headers=_auth_headers(),
                json={"object_key": object_key},
            )
            response.raise_for_status()
            payload = response.json()
            return {"status": str(payload["status"]), "etag": str(payload.get("etag") or "")}
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS upload finalization failed") from exc


async def sign_service_upload(*, filename: str, content_type: str, size_bytes: int, max_bytes: int) -> dict:
    """Sign a worker artifact upload without applying the workspace file limit."""
    if size_bytes <= 0 or size_bytes > max_bytes:
        raise StorageGatewayError("Service artifact size is outside the configured limit")
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.post(
                _gateway_url("/v1/uploads/sign"),
                headers=_auth_headers(),
                json={"filename": filename, "content_type": content_type, "size_bytes": size_bytes},
            )
            response.raise_for_status()
            payload = response.json()
            object_key = str(payload["object_key"])
            return {
                "url": _internal_signed_url(str(payload["url"])),
                "headers": {str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
                "content_ref": f"{OSS_REF_PREFIX}{object_key}",
            }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS service upload signing failed") from exc


async def inspect_object(content_ref: str) -> dict:
    """Verify an uploaded object through a signed ranged GET.

    A one-byte range avoids loading a 100MB object in backend memory. OSS
    returns the authoritative total in Content-Range and an ETag header.
    """
    object_key = object_key_from_ref(content_ref)
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            signed = await client.post(
                _gateway_url("/v1/downloads/sign"),
                headers=_auth_headers(),
                json={"object_key": object_key},
            )
            signed.raise_for_status()
            url = _internal_signed_url(str(signed.json()["url"]))
            async with client.stream("GET", url, headers={"Range": "bytes=0-0"}) as response:
                response.raise_for_status()
                content_range = response.headers.get("content-range", "")
                if "/" in content_range:
                    size = int(content_range.rsplit("/", 1)[1])
                else:
                    size = int(response.headers.get("content-length", "0"))
                return {
                    "size": size,
                    "etag": response.headers.get("etag", "").strip('"'),
                    "content_type": response.headers.get("content-type", "application/octet-stream").split(";", 1)[0],
                }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS uploaded object verification failed") from exc


async def get_signed_download(content_ref: str) -> dict:
    """Issue a signed download used by internal workers and the Skill Runner."""
    object_key = object_key_from_ref(content_ref)
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.post(
                _gateway_url("/v1/downloads/sign"), headers=_auth_headers(), json={"object_key": object_key}
            )
            response.raise_for_status()
            payload = response.json()
            return {
                "url": _internal_signed_url(str(payload["url"])),
                "headers": payload.get("headers") or {},
            }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS download signing failed") from exc


async def get_browser_signed_download(content_ref: str) -> dict:
    """Issue a short-lived public URL for an authenticated browser preview.

    Internal workers use :func:`get_signed_download`, which rewrites the OSS
    hostname to the same-region private endpoint. Browsers cannot resolve that
    private hostname, so this method deliberately preserves the public URL
    returned by the gateway. The URL is still object-scoped and short-lived.
    """
    object_key = object_key_from_ref(content_ref)
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.post(
                _gateway_url("/v1/downloads/sign"), headers=_auth_headers(), json={"object_key": object_key}
            )
            response.raise_for_status()
            payload = response.json()
            return {
                "url": str(payload["url"]),
                "headers": {str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
            }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS browser preview signing failed") from exc


async def stream_signed_download(
    url: str, *, headers: dict[str, str] | None = None, max_bytes: int,
):
    """Proxy a signed OSS response without exposing its internal URL to browsers.

    Browser ``fetch`` cannot follow a redirect to the same-region internal OSS
    hostname.  Keeping that URL server-side also avoids CORS-dependent download
    behaviour while still streaming large workspace files in bounded chunks.
    """
    written = 0
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.storage_gateway_timeout_seconds, read=300), trust_env=False,
        ) as client:
            async with client.stream("GET", url, headers=headers or {}) as response:
                response.raise_for_status()
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > max_bytes:
                    raise StorageGatewayError("OSS object exceeds workspace limit")
                async for chunk in response.aiter_bytes(1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise StorageGatewayError("OSS object exceeds workspace limit")
                    yield chunk
    except StorageGatewayError:
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS streaming download failed") from exc


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


async def download_to_path(content_ref: str, target: Path, *, max_bytes: int) -> int:
    """Stream an OSS object to disk without buffering it in backend memory."""
    object_key = object_key_from_ref(content_ref)
    written = 0
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.storage_gateway_timeout_seconds, read=300), trust_env=False,
        ) as client:
            signed = await client.post(
                _gateway_url("/v1/downloads/sign"), headers=_auth_headers(), json={"object_key": object_key},
            )
            signed.raise_for_status()
            payload = signed.json()
            async with client.stream("GET", _internal_signed_url(str(payload["url"]))) as response:
                response.raise_for_status()
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > max_bytes:
                    raise StorageGatewayError("OSS object exceeds workspace limit")
                with target.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        written += len(chunk)
                        if written > max_bytes:
                            raise StorageGatewayError("OSS object exceeds workspace limit")
                        output.write(chunk)
    except StorageGatewayError:
        target.unlink(missing_ok=True)
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise StorageGatewayError("OSS streaming download failed") from exc
    return written


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


async def list_project_objects(
    *, older_than: datetime, cursor: str | None = None, limit: int = 500,
) -> dict | None:
    """List project-scoped objects for orphan reconciliation when supported.

    Older Storage Gateway deployments intentionally expose no listing API. In
    that case ``None`` is returned and the lifecycle worker skips orphan
    deletion rather than guessing object keys or requiring an OSS AccessKey.
    """
    params: dict[str, str | int] = {
        "older_than": older_than.isoformat(),
        "limit": max(1, min(limit, 1000)),
    }
    if cursor:
        params["cursor"] = cursor
    try:
        async with httpx.AsyncClient(timeout=settings.storage_gateway_timeout_seconds, trust_env=False) as client:
            response = await client.get(
                _gateway_url("/v1/objects"), headers=_auth_headers(), params=params,
            )
            if response.status_code in {404, 405, 501}:
                return None
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise StorageGatewayError("OSS object listing failed") from exc
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        raise StorageGatewayError("OSS object listing failed") from exc
    items = payload if isinstance(payload, list) else payload.get("items", [])
    if not isinstance(items, list):
        raise StorageGatewayError("OSS object listing returned an invalid response")
    normalized: list[dict[str, str | int]] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("object_key"):
            continue
        normalized.append({
            "object_key": str(item["object_key"]),
            "size": int(item.get("size") or item.get("size_bytes") or 0),
            "created_at": str(item.get("created_at") or ""),
        })
    return {
        "items": normalized,
        "next_cursor": None if isinstance(payload, list) else payload.get("next_cursor"),
    }
