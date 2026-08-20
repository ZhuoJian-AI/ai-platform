"""Shared verification helpers for assistant tool-execution claims."""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

_TOOL_SUCCESS_CLAIM_RE = re.compile(
    r"(?:已(?:经)?(?:真实)?调用|调用成功|执行成功|处理成功|已(?:经)?(?:生成|创建|写入|保存|导出)|"
    r"(?:处理|生成|转换|缩放|裁剪|压缩|解压|识别)?已?完成|工具(?:均|全部)?已|全部[^。；\n]{0,20}成功)",
    re.IGNORECASE,
)
_TOOL_ARTIFACT_CLAIM_RE = re.compile(
    r"(?:file[_\s-]?id|文件\s*(?:id|ID)|平台工具输出/|"
    r"(?:spreadsheet|document|presentation|pdf|text|image|image_generation|archive|web)_tool|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})",
    re.IGNORECASE,
)


ExecutionStatus = Literal["verified", "partial", "failed", "legacy_unverified"]


class ExecutionVerificationData(TypedDict):
    status: ExecutionStatus
    tool_calls: int
    succeeded: int
    failed: int


def contains_unverified_tool_success_claim(text: str) -> bool:
    """Return whether text makes a high-confidence claim requiring a tool result."""
    value = (text or "").strip()
    return bool(
        value
        and _TOOL_SUCCESS_CLAIM_RE.search(value)
        and _TOOL_ARTIFACT_CLAIM_RE.search(value)
    )


def classify_execution_verification(
    content: str,
    metadata: dict[str, Any] | None,
) -> ExecutionVerificationData | None:
    """Classify persisted assistant execution from real ``metadata.traces``."""
    traces = (metadata or {}).get("traces") or []
    if not isinstance(traces, list):
        traces = []
    tool_traces = [
        trace
        for trace in traces
        if isinstance(trace, dict)
        and isinstance(trace.get("name"), str)
        and bool(trace.get("name"))
        and isinstance(trace.get("ok"), bool)
    ]
    if tool_traces:
        succeeded = sum(trace["ok"] is True for trace in tool_traces)
        failed = len(tool_traces) - succeeded
        if failed == 0:
            status: ExecutionStatus = "verified"
        elif succeeded:
            status = "partial"
        else:
            status = "failed"
        return {
            "status": status,
            "tool_calls": len(tool_traces),
            "succeeded": succeeded,
            "failed": failed,
        }
    if contains_unverified_tool_success_claim(content):
        return {
            "status": "legacy_unverified",
            "tool_calls": 0,
            "succeeded": 0,
            "failed": 0,
        }
    return None
