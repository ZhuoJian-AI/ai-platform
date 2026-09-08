"""Regression tests for administrator session logout responses."""

import pytest
from httpx import AsyncClient

from app.auth.session_cookies import admin_csrf_cookie_name, admin_session_cookie_name


@pytest.mark.asyncio
async def test_admin_logout_without_session_returns_valid_no_content_response(
    client: AsyncClient,
):
    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""
    cleared_cookies = response.headers.get("set-cookie", "")
    assert admin_session_cookie_name() in cleared_cookies
    assert admin_csrf_cookie_name() in cleared_cookies
    assert "Max-Age=0" in cleared_cookies
