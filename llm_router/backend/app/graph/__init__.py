"""LangGraph 编排底座 —— 请求处理流水线以 StateGraph 表达。

本包将原 ``app/proxy/router.py`` 中的过程式代理流水线（鉴权→权限→DLP 请求扫描
→模型路由→上游代理→审计）重构为一个 LangGraph ``StateGraph``，使请求处理获得
声明式条件路由、节点级可观测与可 checkpoint 的状态，并为后续智能体编排
（``agent_platform``）复用同一套图运行时。

设计要点：
- **编排层 LangGraph 化，叶子逻辑复用**：节点调用现有函数（``scan_request``、
  ``resolve_effective_permissions``、``find_provider``、
  ``proxy_*_request``、``extract_usage_from_body``、``_StreamUsageTracker``）。
- **State 只放可序列化数据**；非序列化运行时句柄（db session / Request / auth）
  走 LangGraph ``context``（``ainvoke``/``astream`` 的 ``context=`` 参数，
  节点内经 ``get_runtime().context`` 取得，不进 checkpoint）。
- 上游 LLM 调用**保留 httpx 字节透传**（复用 adapter），流式经
  ``get_runtime().stream_writer`` + ``astream(stream_mode="custom")`` 实时下发，
  完整保留 Anthropic/OpenAI 协议细节。
"""

from app.graph.builder import build_proxy_graph, get_proxy_graph
from app.graph.runner import run_proxy, stream_proxy

__all__ = ["build_proxy_graph", "get_proxy_graph", "run_proxy", "stream_proxy"]
