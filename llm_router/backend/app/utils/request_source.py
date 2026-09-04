"""Resolve a rate-limit source without trusting caller-controlled proxy headers."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from starlette.requests import Request

from app.config import settings

IPAddress = IPv4Address | IPv6Address


def _trusted_proxy_networks():
    networks = []
    for raw in settings.trusted_proxy_cidrs.split(","):
        value = raw.strip()
        if not value:
            continue
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted(address: IPAddress, networks) -> bool:
    return any(address.version == network.version and address in network for network in networks)


def client_source(request: Request) -> str:
    """Return the right-most untrusted hop from a trusted proxy chain.

    X-Forwarded-For is ignored unless the direct peer belongs to an explicitly
    configured trusted network.  Walking from the right prevents a caller from
    choosing the source bucket by prepending a forged address.
    """

    peer_value = request.client.host if request.client else ""
    try:
        peer = ip_address(peer_value)
    except ValueError:
        return "unknown"
    networks = _trusted_proxy_networks()
    if not networks or not _is_trusted(peer, networks):
        return str(peer)

    forwarded: list[IPAddress] = []
    for raw in request.headers.get("x-forwarded-for", "").split(","):
        value = raw.strip()
        if not value:
            continue
        try:
            forwarded.append(ip_address(value))
        except ValueError:
            return str(peer)
    chain = [*forwarded, peer]
    while chain and _is_trusted(chain[-1], networks):
        chain.pop()
    return str(chain[-1] if chain else peer)
