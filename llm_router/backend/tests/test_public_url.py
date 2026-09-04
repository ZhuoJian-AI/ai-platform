"""DNS-pinned public URL validation tests."""

import socket

import httpx
import pytest

from app.utils.public_url import request_public_http, resolve_public_http_target


@pytest.fixture(autouse=True)
def db_engine():
    """These helpers are pure and do not need PostgreSQL."""

    yield


def _answer(address: str):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


def test_public_target_rejects_any_private_dns_answer(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _answer("93.184.216.34") + _answer("127.0.0.1"),
    )

    with pytest.raises(ValueError, match="private, loopback or reserved"):
        resolve_public_http_target("https://subsystem.example.org/health")


@pytest.mark.asyncio
async def test_public_request_uses_verified_ip_with_original_host_and_sni(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _answer("93.184.216.34"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "subsystem.example.org"
        assert request.extensions["sni_hostname"] == "subsystem.example.org"
        return httpx.Response(200, json={"status": "ok"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    ) as client:
        response = await request_public_http(
            client,
            "GET",
            "https://subsystem.example.org/health",
        )

    assert response.json() == {"status": "ok"}
