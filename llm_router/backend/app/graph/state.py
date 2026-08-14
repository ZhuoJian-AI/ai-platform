"""ProxyState —— LangGraph 代理流水线的可序列化状态 schema。

所有字段必须可序列化（str/int/bool/dict/list/bytes/None），因为状态会在每个
super-step 后被 checkpointer 存储。**非序列化运行时句柄**（db session、FastAPI
Request、AuthenticatedKey）绝不放入 state，而是通过 LangGraph ``context`` 注入
（见 :mod:`app.graph.context`）。**密钥绝不入 state**：上游 API Key 在 proxy
节点内按 ``provider_id`` 从 db 解密、就地使用。
"""

from __future__ import annotations

from typing import TypedDict


class ProxyState(TypedDict, total=False):
    """单次代理请求在图节点间流转的状态。"""

    # ── 请求标识 ──
    request_id: str
    protocol: str  # "anthropic" | "openai"
    is_stream: bool
    start_time: float  # time.monotonic() 起点，供审计计算 latency

    # ── 请求体与模型 ──
    body: dict
    requested_model: str
    resolved_model: str

    # ── 组织架构作用域（UUID 字符串）──
    org_id: str
    dept_id: str | None
    team_id: str | None
    allowed_models: list[str]

    # ── DLP 扫描结果（序列化后的 dict）──
    dlp_request_result: dict
    dlp_response_result: dict

    # ── 路由选定的提供商（仅原语，不含密钥）──
    provider_id: str
    provider_type: str
    base_url: str
    timeout_seconds: int
    max_retries: int

    # ── 上游响应（非流式）──
    response_body: bytes
    status_code: int
    content_type: str
    usage: dict  # {"input_tokens": int|None, "output_tokens": int|None}

    # ── 错误（协议无关的 reason，由 build_error 节点格式化）──
    # 形如 {"status_code": int, "error_type": str, "message": str, "extra": dict|None}
    error: dict | None
