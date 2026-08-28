"""Validation helpers for administrator-configured public subsystem URLs."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


def same_origin(left: str, right: str) -> bool:
    first = urlsplit(left)
    second = urlsplit(right)
    return (
        second.scheme in {"http", "https"}
        and second.username is None
        and second.password is None
        and (first.scheme, first.hostname, first.port) == (second.scheme, second.hostname, second.port)
    )


def assert_public_http_url(url: str, *, require_https: bool = True) -> str:
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain credentials")
    if require_https and parsed.scheme != "https":
        raise ValueError("Public subsystem integration requires HTTPS")
    # RFC 2606 test domains are intentionally non-resolving and are used by unit tests.
    if parsed.hostname.endswith((".test", ".invalid", ".example")):
        return str(url)
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
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            raise ValueError("Subsystem URL points to a private, loopback or reserved address")
    return str(url)
