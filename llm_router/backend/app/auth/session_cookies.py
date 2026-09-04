"""Central cookie names and hardened setters for browser sessions."""

import secrets

from fastapi import Response

from app.config import settings


def admin_session_cookie_name() -> str:
    return "ai_infra_admin_session" if settings.is_development else "__Host-ai-infra-admin"


def user_session_cookie_name() -> str:
    return "ai_infra_user_session" if settings.is_development else "__Host-ai-infra-user"


def admin_csrf_cookie_name() -> str:
    return "ai_infra_admin_csrf"


def oauth_csrf_cookie_name() -> str:
    return "ai_infra_oauth_csrf" if settings.is_development else "__Host-ai-infra-oauth-csrf"


def set_session_cookie(response: Response, name: str, token: str, *, max_age: int) -> None:
    response.set_cookie(
        name,
        token,
        secure=not settings.is_development,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=max_age,
    )


def set_admin_csrf_cookie(response: Response, token: str | None = None) -> str:
    value = token or secrets.token_urlsafe(32)
    response.set_cookie(
        admin_csrf_cookie_name(),
        value,
        secure=not settings.is_development,
        httponly=False,
        samesite="lax",
        path="/",
        max_age=24 * 60 * 60,
    )
    return value


def clear_cookie(response: Response, name: str, *, httponly: bool = True) -> None:
    response.delete_cookie(
        name,
        secure=not settings.is_development,
        httponly=httponly,
        samesite="lax",
        path="/",
    )
