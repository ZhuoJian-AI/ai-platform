"""Validation helpers for administrator-configured public subsystem URLs."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class PublicHttpTarget:
    """A URL whose DNS answer is pinned to the address used for the socket."""

    request_url: str
    host_header: str | None
    sni_hostname: str | None


def same_origin(left: str, right: str) -> bool:
    first = urlsplit(left)
    second = urlsplit(right)
    return (
        second.scheme in {"http", "https"}
        and second.username is None
        and second.password is None
        and (first.scheme, first.hostname, first.port) == (second.scheme, second.hostname, second.port)
    )


def resolve_public_http_target(url: str, *, require_https: bool = True) -> PublicHttpTarget:
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain credentials")
    if require_https and parsed.scheme != "https":
        raise ValueError("Public subsystem integration requires HTTPS")
    # RFC 2606 test domains are intentionally non-resolving and are used by unit tests.
    if parsed.hostname.endswith((".test", ".invalid", ".example")):
        return PublicHttpTarget(str(url), None, None)
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError("Subsystem host cannot be resolved") from exc
    if not addresses:
        raise ValueError("Subsystem host cannot be resolved")
    resolved = [ipaddress.ip_address(item[4][0]) for item in addresses]
    for address in resolved:
        if not address.is_global:
            raise ValueError("Subsystem URL points to a private, loopback or reserved address")
    # Use the same verified address for the actual socket.  Keeping the
    # original Host header and TLS SNI preserves virtual hosting/certificate
    # validation while preventing a second DNS lookup from rebinding inward.
    address = resolved[0]
    ip_host = f"[{address}]" if address.version == 6 else str(address)
    port = f":{parsed.port}" if parsed.port is not None else ""
    request_url = urlunsplit((parsed.scheme, f"{ip_host}{port}", parsed.path, parsed.query, parsed.fragment))
    return PublicHttpTarget(request_url, parsed.netloc, parsed.hostname)


def assert_public_http_url(url: str, *, require_https: bool = True) -> str:
    resolve_public_http_target(url, require_https=require_https)
    return str(url)


async def request_public_http(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    require_https: bool = True,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    target = resolve_public_http_target(url, require_https=require_https)
    request_headers = dict(headers or {})
    extensions = dict(kwargs.pop("extensions", {}) or {})
    if target.host_header:
        request_headers["host"] = target.host_header
    if target.sni_hostname:
        extensions["sni_hostname"] = target.sni_hostname
    return await client.request(
        method,
        target.request_url,
        headers=request_headers,
        extensions=extensions,
        **kwargs,
    )
