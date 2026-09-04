from starlette.requests import Request

from app.config import settings
from app.utils.request_source import client_source


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (peer, 12345),
        "server": ("testserver", 443),
        "scheme": "https",
        "query_string": b"",
    })


def test_untrusted_peer_cannot_spoof_forwarded_source(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    assert client_source(_request("203.0.113.8", "198.51.100.7")) == "203.0.113.8"


def test_trusted_proxy_chain_returns_rightmost_untrusted_client(monkeypatch):
    monkeypatch.setattr(
        settings,
        "trusted_proxy_cidrs",
        "10.0.0.0/8,172.16.0.0/12",
    )
    request = _request("10.0.0.4", "192.0.2.99, 198.51.100.7, 172.20.0.9")
    assert client_source(request) == "198.51.100.7"


def test_malformed_forwarding_fails_back_to_direct_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    assert client_source(_request("10.0.0.4", "not-an-ip")) == "10.0.0.4"
