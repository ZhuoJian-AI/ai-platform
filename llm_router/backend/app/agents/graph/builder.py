"""智能体运行时 StateGraph 构建器。

图拓扑（线性；retrieve_rag / load_memory / extract_memory / judge 在未配置时 no-op）：

    START → load_config → retrieve_rag → load_memory → agent_loop
          → save_memory → extract_memory → judge → write_run_log → END

agent_loop 节点内部完成 LLM ↔ 工具 多步循环（步级事件经 stream_writer 下发）。
InMemorySaver 按 ``thread_id = session_id`` 隔离各会话状态。
agent / general 两模式共用同一图（节点内按 state["mode"] 分支）。
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.graph.nodes import (
    agent_loop,
    extract_memory,
    judge,
    load_config,
    load_memory,
    retrieve_rag,
    save_memory,
    write_run_log,
)
from app.agents.graph.state import AgentState


def build_agent_graph():
    """构建并编译智能体运行时 StateGraph。"""
    graph = StateGraph(AgentState)

    graph.add_node("load_config", load_config)
    graph.add_node("retrieve_rag", retrieve_rag)
    graph.add_node("load_memory", load_memory)
    graph.add_node("agent_loop", agent_loop)
    graph.add_node("save_memory", save_memory)
    graph.add_node("extract_memory", extract_memory)
    graph.add_node("judge", judge)
    graph.add_node("write_run_log", write_run_log)

    graph.add_edge(START, "load_config")
    graph.add_edge("load_config", "retrieve_rag")
    graph.add_edge("retrieve_rag", "load_memory")
    graph.add_edge("load_memory", "agent_loop")
    graph.add_edge("agent_loop", "save_memory")
    graph.add_edge("save_memory", "extract_memory")
    graph.add_edge("extract_memory", "judge")
    graph.add_edge("judge", "write_run_log")
    graph.add_edge("write_run_log", END)

    return graph.compile(checkpointer=InMemorySaver())


@lru_cache(maxsize=1)
def get_agent_graph():
    """进程级单例编译图。InMemorySaver 按 thread_id=session_id 隔离各会话。"""
    return build_agent_graph()
