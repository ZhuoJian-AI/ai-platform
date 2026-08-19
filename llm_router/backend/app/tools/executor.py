"""Tool executor — invoke an external system endpoint with auth + logging.

按 ``ToolEndpoint`` 定义发起 httpx 调用，注入连接器鉴权，记录 ``ToolCallLog``。
agent 的 execute_tools 节点与测试广场均经此入口调用外部 API。

鉴权配置（auth_config）以加密形式存于连接器；此处解密后按 auth_type 注入请求。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector import ToolConnector, ToolEndpoint
from app.models.tool_call_log import ToolCallLog
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key

logger = structlog.get_logger()


def encrypt_auth_config(config: dict) -> str:
    """加密鉴权配置 dict（JSON 序列化后 AES-256-GCM）。"""
    return encrypt_provider_api_key(json.dumps(config, ensure_ascii=False))


def decrypt_auth_config(encrypted: str) -> dict:
    """解密鉴权配置。空串返回空 dict。"""
    if not encrypted:
        return {}
    try:
        return json.loads(decrypt_provider_api_key(encrypted))
    except Exception:  # noqa: BLE001
        return {}


def _apply_auth(headers: dict, params: dict, connector: ToolConnector) -> None:
    """按 auth_type 把解密后的鉴权配置注入 headers/params。"""
    cfg = decrypt_auth_config(connector.auth_config_encrypted)
    at = connector.auth_type
    if at == "bearer":
        headers["authorization"] = f"Bearer {cfg.get('token', '')}"
    elif at == "apikey":
        # header_key 可配置，默认 X-API-Key
        hk = cfg.get("header_key", "X-API-Key")
        headers[hk] = str(cfg.get("api_key", ""))
    elif at == "basic":
        import base64
        userpass = f"{cfg.get('username','')}:{cfg.get('password','')}"
        headers["authorization"] = "Basic " + base64.b64encode(userpass.encode()).decode()
    elif at == "oauth":
        # 简化：直接用预置 access_token 作 Bearer
        headers["authorization"] = f"Bearer {cfg.get('access_token', '')}"
    # none: 不注入


@dataclass
class ExecutionResult:
    status_code: int | None
    latency_ms: int
    body: Any
    error: str | None


async def execute_endpoint(
    db: AsyncSession,
    *,
    org_id: UUID,
    connector: ToolConnector,
    endpoint: ToolEndpoint,
    params: dict | None = None,
    skill_id: UUID | None = None,
) -> ExecutionResult:
    """执行单个端点调用，记录 ToolCallLog。"""
    params = params or {}
    headers: dict[str, str] = {"content-type": "application/json"}
    query: dict[str, Any] = {}
    body: Any = None

    _apply_auth(headers, query, connector)

    method = endpoint.method.upper()

    # 路径参数替换：endpoint.path 形如 /api/v1/styles/{style_code}，LLM 把 style_code
    # 当普通入参传值，这里将其替换进 URL 占位符并从 query/body 参数中移除，避免
    # 占位符字面透传导致 mock 收到 /styles/{style_code} 而返回 404。
    path = endpoint.path or ""
    consumed: set[str] = set()
    if "{" in path:
        for pname, pvalue in params.items():
            placeholder = "{" + str(pname) + "}"
            if placeholder in path and pvalue is not None:
                path = path.replace(placeholder, quote(str(pvalue), safe=""))
                consumed.add(pname)
    remaining = {k: v for k, v in params.items() if k not in consumed}

    # 简化参数放置：GET → query；其余 → JSON body（仅未用于 path 的剩余参数）
    if method == "GET":
        query.update(remaining)
    else:
        body = remaining

    url = connector.base_url.rstrip("/") + "/" + path.lstrip("/")
    start = time.monotonic()
    status_code: int | None = None
    resp_body: Any = None
    error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(method, url, headers=headers, params=query or None, json=body)
        status_code = resp.status_code
        try:
            resp_body = resp.json()
        except Exception:  # noqa: BLE001
            resp_body = resp.text
    except httpx.HTTPError as exc:
        error = str(exc)
        logger.warning("tool_call_http_error", connector=connector.slug, endpoint=endpoint.name, error=error)

    latency_ms = int((time.monotonic() - start) * 1000)

    # 记日志。用 SAVEPOINT 隔离 ToolCallLog 写入：日志落库失败（如约束冲突）
    # 只回滚保存点，不污染 run 主事务——否则后续 save_memory/write_run_log 的
    # flush 抛 PendingRollbackError，本轮 assistant 消息会被一并回滚而消失。
    # 日志只是附属记录，写失败不应让已成功取到的工具结果变成「tool error」。
    preview = json.dumps(resp_body, ensure_ascii=False)[:2000] if resp_body is not None else None
    try:
        async with db.begin_nested():
            db.add(ToolCallLog(
                organization_id=str(org_id),
                connector_id=str(connector.id),
                endpoint_id=str(endpoint.id),
                skill_id=skill_id,
                method=method,
                path=endpoint.path,
                params=params,
                status_code=status_code,
                latency_ms=latency_ms,
                error=error,
                response_preview=preview,
            ))
            await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool_call_log_persist_failed", endpoint=endpoint.name, error=str(exc))

    return ExecutionResult(status_code=status_code, latency_ms=latency_ms, body=resp_body, error=error)
