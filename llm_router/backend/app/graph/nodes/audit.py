"""write_audit 节点 —— 写入审计日志（含 token 用量与 DLP 命中）。

等价于原 ``proxy/router.py`` 的 ``_write_audit_log`` / ``_make_audit_writer``。
图节点顺序保证：write_audit 在 proxy_upstream（或 build_error）之后执行，故非流式
可在返回响应前同步写、流式可在流结束后写（消费方迭代 ``astream`` 至结束即图完成）。
db commit 仍由 ``get_db`` 依赖退出时完成，生命周期与原代码一致。
"""

from __future__ import annotations

import time

import structlog

from app.graph.context import get_deps
from app.graph.state import ProxyState
from app.models.audit_log import AuditLog

logger = structlog.get_logger()


async def write_audit(state: ProxyState) -> dict:
    """写入审计日志。"""
    deps = get_deps()
    db = deps["db"]
    auth = deps["auth"]

    err = state.get("error")
    usage = state.get("usage") or {}
    dlp_result = state.get("dlp_request_result") or {}
    dlp_resp_result = state.get("dlp_response_result") or {}

    # 错误路径下 status_code 取自 error；成功路径取自 proxy 回填的 status_code
    status_code = state.get("status_code")
    if status_code is None and err:
        status_code = err.get("status_code")

    # DLP 命中：请求侧 block 命中 + 响应侧 block 命中（流式/非流式）
    dlp_violations = list(dlp_result.get("violations", []) if dlp_result.get("blocked") else [])
    if dlp_resp_result.get("blocked"):
        dlp_violations.extend(dlp_resp_result.get("violations", []))

    latency_ms = int((time.monotonic() - state.get("start_time", time.monotonic())) * 1000)

    log = AuditLog(
        request_id=state.get("request_id", ""),
        api_key_id=str(auth.api_key.id),
        organization_id=str(auth.organization_id),
        department_id=str(auth.department_id) if auth.department_id else None,
        team_id=str(auth.team_id) if auth.team_id else None,
        provider_id=state.get("provider_id"),
        event_type="proxy_request",
        direction="inbound",
        model_requested=state.get("requested_model"),
        model_served=state.get("resolved_model"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_ms=latency_ms,
        status_code=status_code,
        dlp_violations=dlp_violations,
        error_message=err.get("message") if err else None,
    )
    db.add(log)
    await db.flush()
    return {}
