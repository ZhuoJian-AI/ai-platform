"""OAuth 2.1 endpoints used by public MCP clients such as Codex."""

from __future__ import annotations

import hmac
import html
import secrets
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.login_throttle import (
    assert_login_allowed,
    clear_login_failures,
    record_login_failure,
)
from app.auth.session_cookies import (
    clear_cookie,
    oauth_csrf_cookie_name,
    set_session_cookie,
    user_session_cookie_name,
)
from app.auth.user_auth import decode_user_token
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.services import oauth_service
from app.services.user_service import login_user
from app.utils.request_source import client_source

router = APIRouter(prefix="/oauth")
well_known_router = APIRouter()


class ClientRegistrationRequest(BaseModel):
    client_name: str = Field(..., min_length=1, max_length=255)
    redirect_uris: list[str] = Field(..., min_length=1, max_length=10)
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str = "none"


def _oauth_error(exc: oauth_service.OAuthProtocolError) -> JSONResponse:
    response = JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "error_description": exc.description},
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    if exc.status_code == 401:
        response.headers["WWW-Authenticate"] = 'Bearer error="invalid_token"'
    return response


def _append_query(uri: str, **values: str | None) -> str:
    parsed = urlparse(uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in values.items() if value is not None)
    return urlunparse(parsed._replace(query=urlencode(query)))


async def _session_user(request: Request, db: AsyncSession) -> User | None:
    raw = request.cookies.get(user_session_cookie_name(), "")
    claims = decode_user_token(raw) if raw else None
    if claims is None:
        return None
    try:
        user = await db.get(User, UUID(str(claims["sub"])))
    except (KeyError, ValueError):
        return None
    if user is None or not user.is_active or user.deleted_at is not None:
        return None
    organization = await db.get(Organization, user.organization_id)
    if organization is None or organization.deleted_at is not None:
        return None
    if int(claims.get("auth_epoch", -1)) != user.auth_epoch or user.must_change_password:
        return None
    return user


async def _authorize_validated(
    db: AsyncSession,
    request: Request,
    *,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    scope: str | None,
):
    try:
        return await oauth_service.validate_authorization_request(
            db,
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
            scope=scope,
            request=request,
        )
    except oauth_service.OAuthProtocolError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.description) from exc


async def _complete_authorization(
    db: AsyncSession,
    request: Request,
    *,
    user: User,
    client_id: str,
    redirect_uri: str,
    resource: str,
    scope: str,
    code_challenge: str,
    state: str | None,
) -> RedirectResponse:
    organization_id = oauth_service.parse_resource_org(resource, request)
    if user.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="This account does not belong to the requested enterprise")
    code = await oauth_service.issue_authorization_code(
        db,
        client_id=client_id,
        redirect_uri=redirect_uri,
        user=user,
        resource=resource,
        scope=scope,
        code_challenge=code_challenge,
    )
    response = RedirectResponse(_append_query(redirect_uri, code=code, state=state), status_code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


def _login_page(
    *,
    client_name: str,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    scope: str,
    state: str | None,
    csrf_token: str,
    error: str | None = None,
) -> HTMLResponse:
    hidden = {
        "decision": "login",
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "resource": resource,
        "scope": scope,
        "state": state or "",
        "csrf_token": csrf_token,
    }
    fields = "".join(
        f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value, quote=True)}">'
        for key, value in hidden.items()
    )
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>连接个人 AI 助手</title><style>
body{{margin:0;background:#f5f7fb;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#1f2937}}
main{{max-width:420px;margin:10vh auto;background:white;padding:32px;border-radius:14px;
box-shadow:0 12px 40px #18223b18}}
h1{{font-size:22px;margin:0 0 8px}}p{{color:#64748b;line-height:1.6}}
label{{display:block;margin:16px 0 6px;font-weight:600}}
input[type=text],input[type=password]{{box-sizing:border-box;width:100%;padding:11px;
border:1px solid #cbd5e1;border-radius:8px}}
button{{width:100%;margin-top:22px;padding:12px;border:0;border-radius:8px;
background:#4f46e5;color:white;font-weight:700;cursor:pointer}}
.error{{color:#b91c1c;background:#fef2f2;padding:9px;border-radius:7px}}small{{display:block;color:#64748b;margin-top:18px}}
</style></head><body><main><h1>连接个人 AI 助手</h1>
<p><strong>{html.escape(client_name)}</strong> 请求使用你在本企业内已经获授权的能力。
请用普通员工账号登录；不需要管理员账号或 API Key。</p>
{error_html}<form method="post" action="/api/v1/oauth/authorize">{fields}
<label for="username">用户名</label>
<input id="username" name="username" type="text" autocomplete="username" required autofocus>
<label for="password">密码</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">登录并连接</button></form>
<small>连接只授予当前企业资源；模型供应商密钥不会发送给客户端。</small></main></body></html>"""
    response = HTMLResponse(body)
    response.set_cookie(
        oauth_csrf_cookie_name(),
        csrf_token,
        secure=not settings.is_development,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=600,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["X-Frame-Options"] = "DENY"
    return response


def _consent_page(
    *,
    client_name: str,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    scope: str,
    state: str | None,
    csrf_token: str,
) -> HTMLResponse:
    hidden = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "resource": resource,
        "scope": scope,
        "state": state or "",
        "csrf_token": csrf_token,
    }
    fields = "".join(
        f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value, quote=True)}">'
        for key, value in hidden.items()
    )
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>确认连接个人 AI 助手</title><style>
body{{margin:0;background:#f5f7fb;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#1f2937}}
main{{max-width:440px;margin:10vh auto;background:#fff;padding:32px;
border-radius:14px;box-shadow:0 12px 40px #18223b18}}
h1{{font-size:22px;margin:0 0 12px}}p{{color:#64748b;line-height:1.65}}.actions{{display:flex;gap:12px;margin-top:24px}}
button{{flex:1;padding:12px;border-radius:8px;border:1px solid #cbd5e1;background:#fff;font-weight:700;cursor:pointer}}
button[value=approve]{{background:#4f46e5;color:#fff;border-color:#4f46e5}}
</style></head><body><main><h1>确认连接</h1>
<p><strong>{html.escape(client_name)}</strong> 请求以你的当前企业角色使用已授权的平台工具。</p>
<p>权限范围：{html.escape(scope)}。模型供应商密钥不会发送给客户端。</p>
<form method="post" action="/api/v1/oauth/authorize">{fields}<div class="actions">
<button name="decision" value="deny" type="submit">取消</button>
<button name="decision" value="approve" type="submit">允许连接</button>
</div></form></main></body></html>"""
    response = HTMLResponse(body)
    response.set_cookie(
        oauth_csrf_cookie_name(),
        csrf_token,
        secure=not settings.is_development,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=600,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["X-Frame-Options"] = "DENY"
    return response


@router.post("/register")
async def register_client(
    data: ClientRegistrationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    expected_grants = {"authorization_code", "refresh_token"}
    if set(data.grant_types) != expected_grants:
        return _oauth_error(oauth_service.OAuthProtocolError(
            "invalid_client_metadata",
            "grant_types must be authorization_code and refresh_token",
        ))
    if data.response_types != ["code"] or data.token_endpoint_auth_method != "none":
        return _oauth_error(oauth_service.OAuthProtocolError("invalid_client_metadata", "public PKCE clients only"))
    try:
        client = await oauth_service.register_public_client(
            db,
            client_name=data.client_name,
            redirect_uris=data.redirect_uris,
            registration_source=client_source(request),
        )
    except oauth_service.OAuthProtocolError as exc:
        return _oauth_error(exc)
    return {
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()) if client.created_at else 0,
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "response_types": client.response_types,
        "token_endpoint_auth_method": "none",
    }


@router.get("/authorize")
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    scope: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    client, _organization_id, normalized_scope = await _authorize_validated(
        db, request,
        response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
        code_challenge=code_challenge, code_challenge_method=code_challenge_method,
        resource=resource, scope=scope,
    )
    user = await _session_user(request, db)
    if user is not None:
        return _consent_page(
            client_name=client.client_name,
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
            scope=normalized_scope,
            state=state,
            csrf_token=secrets.token_urlsafe(32),
        )
    return _login_page(
        client_name=client.client_name,
        response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
        code_challenge=code_challenge, code_challenge_method=code_challenge_method,
        resource=resource, scope=normalized_scope, state=state,
        csrf_token=secrets.token_urlsafe(32),
    )


@router.post("/authorize")
async def authorize_login(
    request: Request,
    response_type: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...),
    resource: str = Form(...),
    scope: str = Form(...),
    state: str = Form(""),
    csrf_token: str = Form(...),
    decision: str = Form("login"),
    username: str | None = Form(None),
    password: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    client, organization_id, normalized_scope = await _authorize_validated(
        db, request,
        response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
        code_challenge=code_challenge, code_challenge_method=code_challenge_method,
        resource=resource, scope=scope,
    )
    cookie_token = request.cookies.get(oauth_csrf_cookie_name(), "")
    if not cookie_token or not hmac.compare_digest(cookie_token, csrf_token):
        raise HTTPException(status_code=403, detail="Authorization form expired; start the connection again")
    if decision == "deny":
        response = RedirectResponse(
            _append_query(redirect_uri, error="access_denied", state=state or None),
            status_code=302,
        )
        clear_cookie(response, oauth_csrf_cookie_name())
        response.headers["Cache-Control"] = "no-store"
        return response
    if decision == "approve":
        user = await _session_user(request, db)
        if user is None:
            return _login_page(
                client_name=client.client_name,
                response_type=response_type,
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                resource=resource,
                scope=normalized_scope,
                state=state,
                csrf_token=secrets.token_urlsafe(32),
                error="登录已过期，请重新登录",
            )
        response = await _complete_authorization(
            db,
            request,
            user=user,
            client_id=client_id,
            redirect_uri=redirect_uri,
            resource=resource,
            scope=normalized_scope,
            code_challenge=code_challenge,
            state=state or None,
        )
        clear_cookie(response, oauth_csrf_cookie_name())
        return response
    if decision != "login" or not username or not password:
        raise HTTPException(status_code=400, detail="Invalid authorization decision")
    identity = f"{organization_id}:{username}"
    source = client_source(request)
    await assert_login_allowed("oauth", identity, source)
    login = await login_user(db, organization_id, username, password)
    if login is None:
        await record_login_failure("oauth", identity, source)
        return _login_page(
            client_name=client.client_name,
            response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
            code_challenge=code_challenge, code_challenge_method=code_challenge_method,
            resource=resource, scope=normalized_scope, state=state,
            csrf_token=secrets.token_urlsafe(32), error="用户名或密码不正确",
        )
    await clear_login_failures("oauth", identity, source)
    user = await db.get(User, UUID(str(login.user.id)))
    if user is None:
        raise HTTPException(status_code=401, detail="User account is unavailable")
    if user.must_change_password:
        return _login_page(
            client_name=client.client_name,
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
            scope=normalized_scope,
            state=state,
            csrf_token=secrets.token_urlsafe(32),
            error="请先从企业员工入口修改初始密码，再连接个人 AI 助手",
        )
    response = await _complete_authorization(
        db, request, user=user, client_id=client_id, redirect_uri=redirect_uri,
        resource=resource, scope=normalized_scope, code_challenge=code_challenge, state=state or None,
    )
    set_session_cookie(response, user_session_cookie_name(), login.access_token, max_age=24 * 60 * 60)
    clear_cookie(response, oauth_csrf_cookie_name())
    return response


@router.post("/token")
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    client_id: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
    resource: str = Form(...),
    scope: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        if grant_type == "authorization_code":
            if not code or not redirect_uri or not code_verifier:
                raise oauth_service.OAuthProtocolError(
                    "invalid_request",
                    "code, redirect_uri and code_verifier are required",
                )
            pair = await oauth_service.exchange_authorization_code(
                db, code=code, client_id=client_id, redirect_uri=redirect_uri,
                code_verifier=code_verifier, resource=resource, request=request,
            )
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise oauth_service.OAuthProtocolError("invalid_request", "refresh_token is required")
            pair = await oauth_service.rotate_refresh_token(
                db, refresh_token=refresh_token, client_id=client_id,
                resource=resource, scope=scope, request=request,
            )
        else:
            raise oauth_service.OAuthProtocolError("unsupported_grant_type", "unsupported grant_type")
    except oauth_service.OAuthProtocolError as exc:
        return _oauth_error(exc)
    response = JSONResponse({
        "access_token": pair.access_token,
        "token_type": "Bearer",
        "expires_in": pair.expires_in,
        "refresh_token": pair.refresh_token,
        "scope": pair.scope,
    })
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@well_known_router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata(request: Request):
    base = oauth_service.issuer(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/api/v1/oauth/authorize",
        "token_endpoint": f"{base}/api/v1/oauth/token",
        "registration_endpoint": f"{base}/api/v1/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [oauth_service.MCP_SCOPE],
        "resource_parameter_supported": True,
    }


@well_known_router.get("/.well-known/oauth-protected-resource/mcp/organizations/{organization_id}")
async def protected_resource_metadata(organization_id: UUID, request: Request):
    resource = oauth_service.resource_for_org(organization_id, request)
    return {
        "resource": resource,
        "authorization_servers": [oauth_service.issuer(request)],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [oauth_service.MCP_SCOPE],
        "resource_name": "AI Infra enterprise MCP capabilities",
    }
