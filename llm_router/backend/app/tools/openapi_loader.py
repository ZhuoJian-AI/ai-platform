"""Load and validate OpenAPI documents used by connector onboarding."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx
import yaml

MAX_OPENAPI_BYTES = 2_000_000


def parse_openapi_document(content: str) -> dict:
    if len(content.encode("utf-8")) > MAX_OPENAPI_BYTES:
        raise ValueError("OpenAPI document exceeds the 2 MB limit")

    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        try:
            value = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ValueError("OpenAPI document is not valid JSON or YAML") from exc

    if not isinstance(value, dict):
        raise ValueError("OpenAPI document must be an object")
    if not value.get("openapi") and not value.get("swagger"):
        raise ValueError("OpenAPI document is missing the openapi/swagger version")
    if not isinstance(value.get("paths"), dict) or not value["paths"]:
        raise ValueError("OpenAPI document has no paths")
    return value


async def fetch_openapi_document(url: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("OpenAPI URL must be an http(s) URL without embedded credentials")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=True,
        headers={"user-agent": "AI-Platform-OpenAPI-Inspector/1.0"},
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            declared_size = response.headers.get("content-length")
            if declared_size and int(declared_size) > MAX_OPENAPI_BYTES:
                raise ValueError("OpenAPI document exceeds the 2 MB limit")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_OPENAPI_BYTES:
                    raise ValueError("OpenAPI document exceeds the 2 MB limit")
                chunks.append(chunk)

    return parse_openapi_document(b"".join(chunks).decode("utf-8-sig"))
