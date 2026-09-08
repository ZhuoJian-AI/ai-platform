"""Compatibility coverage for the retired MCP/OAuth Skill Pack surface."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/oauth/register"),
        ("GET", "/api/v1/oauth/authorize"),
        ("POST", "/api/v1/oauth/token"),
        ("GET", "/.well-known/oauth-authorization-server"),
        (
            "GET",
            "/.well-known/oauth-protected-resource/mcp/organizations/"
            "00000000-0000-0000-0000-000000000001",
        ),
    ],
)
async def test_mcp_oauth_routes_return_stable_chinese_retirement(
    client: AsyncClient,
    method: str,
    path: str,
):
    response = await client.request(method, path)
    assert response.status_code == 410
    assert response.json()["detail"] == {
        "code": "feature_retired",
        "message": "MCP/OAuth Skill Pack 已下线；请使用平台内置助手与用户上传 Skill。",
        "retryable": False,
    }
