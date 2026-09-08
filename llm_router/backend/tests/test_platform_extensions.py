"""Compatibility coverage for the retired DSH extension market."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/platform/extensions/overview"),
        ("GET", "/api/v1/platform/extensions/catalog"),
        ("POST", "/api/v1/platform/extensions/import/npm"),
        ("POST", "/api/v1/platform/extensions/import/github"),
        ("POST", "/api/v1/platform/extensions/releases"),
        ("POST", "/api/v1/platform/extensions/internal/artifacts/sign"),
    ],
)
async def test_extension_market_routes_return_stable_retirement(
    client: AsyncClient,
    method: str,
    path: str,
):
    response = await client.request(method, path)
    assert response.status_code == 410
    detail = response.json()["detail"]
    assert detail["code"] == "feature_retired"
    assert "外部扩展与市场" in detail["message"]
    assert detail["retryable"] is False
