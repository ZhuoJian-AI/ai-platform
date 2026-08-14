"""DLP 节点 —— 请求侧与响应侧安全围栏扫描。

- ``dlp_request``：等价于原 ``proxy/router.py`` 中「提取请求文本 → scan_request →
  block/redact/warn/log」一段。命中 block 规则时设置 ``state.error``（携带命中规则
  详情，受 ``settings.dlp_expose_matches_in_error`` 开关控制），由条件边导向 build_error。
- ``dlp_response``：扫描非流式响应体（``scan_response``），block 则不转发泄露响应、
  redact 则用脱敏文本替换 response_body。流式响应 DLP 在 proxy 节点内联完成
  （见 ``app.dlp.stream_filter``）。
"""

from __future__ import annotations

import structlog

from app.config import settings
from app.dlp.engine import DLPMatch, DLPResult
from app.dlp.scanner import scan_request, scan_response
from app.graph.context import get_deps
from app.graph.state import ProxyState

logger = structlog.get_logger()


async def dlp_request(state: ProxyState) -> dict:
    """扫描请求文本，应用 DLP 动作。"""
    body = state.get("body", {})
    protocol = state.get("protocol", "openai")
    request_id = state.get("request_id", "")

    request_text = _extract_text_from_messages(body.get("messages", []), protocol)
    if not request_text:
        return {}

    deps = get_deps()
    db = deps["db"]
    result = await scan_request(
        db,
        request_text,
        state.get("org_id", ""),
        state.get("dept_id"),
        state.get("team_id"),
    )

    dlp_dict = _serialize_dlp_result(result)

    if result.blocked:
        logger.warning(
            "dlp_request_blocked",
            request_id=request_id,
            protocol=protocol,
            violations=len(result.violations),
            matched_rules=[_match_log_dict(v) for v in result.violations],
        )
        error_type = "invalid_request_error" if protocol == "anthropic" else "dlp_violation"
        return {
            "dlp_request_result": dlp_dict,
            "error": {
                "status_code": 400,
                "error_type": error_type,
                "message": "Request blocked by DLP security policy",
                "extra": _dlp_error_extra(result),
            },
        }

    _log_dlp_non_blocking(result, request_id, protocol)
    return {"dlp_request_result": dlp_dict}


def route_after_dlp(state: ProxyState) -> str:
    """DLP 扫描后的条件路由：blocked → build_error，否则 → resolve_route。"""
    return "build_error" if state.get("error") else "resolve_route"


async def dlp_response(state: ProxyState) -> dict:
    """扫描非流式响应体，应用响应方向 DLP 动作（block/redact）。

    在 proxy_upstream 之后执行（仅非流式路径；流式响应 DLP 在 proxy 节点内联完成）。
    命中 block 规则时设置 ``state.error``，由条件边导向 build_error（不转发泄露的响应）；
    命中 redact 规则时用脱敏后的文本替换 response_body。无规则时原样放行。
    """
    body_bytes = state.get("response_body")
    if not body_bytes:
        return {}

    deps = get_deps()
    db = deps["db"]
    protocol = state.get("protocol", "openai")
    request_id = state.get("request_id", "")

    if isinstance(body_bytes, (bytes, bytearray)):
        text = body_bytes.decode("utf-8", errors="replace")
    else:
        text = str(body_bytes)
    result = await scan_response(
        db,
        text,
        state.get("org_id", ""),
        state.get("dept_id"),
        state.get("team_id"),
    )
    dlp_dict = _serialize_dlp_result(result)

    if result.blocked:
        logger.warning(
            "dlp_response_blocked",
            request_id=request_id,
            protocol=protocol,
            violations=len(result.violations),
            matched_rules=[_match_log_dict(v) for v in result.violations],
        )
        error_type = "invalid_request_error" if protocol == "anthropic" else "dlp_violation"
        return {
            "dlp_response_result": dlp_dict,
            "error": {
                "status_code": 400,
                "error_type": error_type,
                "message": "Response blocked by DLP security policy",
                "extra": _dlp_error_extra(result),
            },
        }

    update: dict = {"dlp_response_result": dlp_dict}
    if result.redacted_text and result.redacted_text != text:
        update["response_body"] = result.redacted_text.encode("utf-8")
    return update


def route_after_dlp_response(state: ProxyState) -> str:
    """响应 DLP 后的条件路由：blocked → build_error，否则 → write_audit。"""
    return "build_error" if state.get("error") else "write_audit"


# ── 辅助函数（移植自原 proxy/router.py，保持行为一致）──────────────────────


def _serialize_dlp_result(result: DLPResult) -> dict:
    """将 DLPResult 序列化为可入 state 的 dict。"""
    return {
        "blocked": result.blocked,
        "violations": [_match_dict(v) for v in result.violations],
        "warnings": [_match_dict(v) for v in result.warnings],
        "logged": [_match_dict(v) for v in result.logged],
        "has_violations": result.has_violations,
    }


def _match_dict(v: DLPMatch) -> dict:
    return {
        "rule_id": str(v.rule_id),
        "rule_name": v.rule_name,
        "severity": v.severity,
        "action": v.action,
        "matched_text_redacted": v.matched_text_redacted,
        "start": v.start,
        "end": v.end,
    }


def _match_log_dict(v: DLPMatch) -> dict:
    """日志用字段（与原代码一致）。"""
    return {
        "rule_id": str(v.rule_id),
        "rule_name": v.rule_name,
        "severity": v.severity,
        "action": v.action,
        "matched_text_redacted": v.matched_text_redacted,
        "start": v.start,
        "end": v.end,
    }


def _dlp_error_extra(dlp_result: DLPResult) -> dict | None:
    """构建错误响应中附带的 DLP 命中规则详情。

    受 ``settings.dlp_expose_matches_in_error`` 开关控制；关闭时返回 None，
    错误响应只保留通用的 "Request blocked by DLP security policy" 文案。
    仅返回规则名/严重级/动作/脱敏命中片段，不泄露 rule_id 与原文位置。
    """
    if not settings.dlp_expose_matches_in_error:
        return None
    return {
        "dlp": {
            "matched_rules": [
                {
                    "rule_name": v.rule_name,
                    "severity": v.severity,
                    "action": v.action,
                    "matched_text_redacted": v.matched_text_redacted,
                }
                for v in dlp_result.violations
            ],
        }
    }


def _log_dlp_non_blocking(dlp_result: DLPResult, request_id: str, protocol: str) -> None:
    """记录非拦截型 DLP 命中（action=warn/log）。"""
    matches = list(dlp_result.warnings) + list(dlp_result.logged)
    if not matches:
        return
    logger.info(
        "dlp_request_flagged",
        request_id=request_id,
        protocol=protocol,
        warnings=len(dlp_result.warnings),
        logged=len(dlp_result.logged),
        matched_rules=[
            {
                "rule_id": str(m.rule_id),
                "rule_name": m.rule_name,
                "severity": m.severity,
                "action": m.action,
                "matched_text_redacted": m.matched_text_redacted,
            }
            for m in matches
        ],
    )


def _extract_text_from_messages(messages: list[dict], protocol: str) -> str:
    """从请求消息中提取纯文本用于 DLP 扫描。

    除文本块外，还会把附件块的 ``media_type`` 与 ``filename`` 投影到待扫描文本，
    使文件附件类规则（如 Excel 附件）能命中真实附件——二进制内容本身不扫描。
    """
    texts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                else:
                    texts.extend(_extract_attachment_hints(block))
    # protocol 参数保留以兼容调用方签名；两种协议的文本提取逻辑一致。
    _ = protocol
    return " ".join(texts)[:100_000]  # 限制扫描长度


def _extract_attachment_hints(block: dict) -> list[str]:
    """从单个非文本内容块中提取可用于 DLP 扫描的附件元数据（MIME / 文件名）。

    覆盖 Anthropic（document/image，source.media_type）与 OpenAI
    （image_url / file / input_file）常见结构。
    """
    hints: list[str] = []

    source = block.get("source")
    if isinstance(source, dict) and source.get("media_type"):
        hints.append(str(source["media_type"]))

    for key in ("media_type", "filename", "name", "title"):
        val = block.get(key)
        if val:
            hints.append(str(val))

    for nested_key in ("file", "input_file"):
        nested = block.get(nested_key)
        if isinstance(nested, dict):
            for key in ("filename", "name"):
                val = nested.get(key)
                if val:
                    hints.append(str(val))

    return hints
