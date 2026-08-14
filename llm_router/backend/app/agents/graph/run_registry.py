"""进程内 run 注册表 —— detach 执行的 run 句柄，供「断连续接」回放 + 续接 live。

为什么需要：``runner.py`` 的 ``stream_general_agent`` 把图执行 detach 到后台
``asyncio.create_task``，执行生命周期不再绑 SSE 连接。客户端断连后想重连续接，
需要拿到该 run 已产出的事件 buffer（回放）+ live queue（续接）。本注册表即此中介。

单进程内存态（单 uvicorn worker，见 Dockerfile），重启即失——由 resume 端点的
「无 live handle + agent_runs.status=running」分支兜底为 interrupted，不丢已落库事件。

线程/并发模型：
- ``publish`` 由后台 runner 单写；``buffer`` 与 ``queue`` 仅写者 + 多读者。
- ``queue`` 是 ``asyncio.Queue``，读者 ``get()`` 直到 ``done`` + 投递哨兵。
- 同一 task 一次只允许一个 active run（POST /run 对运行中任务 = 重连，不起新图）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class RunHandle:
    """一次 detach 执行的句柄。payload 统一存 SSE 已格式化的 ``data: {json}\\n\\n`` 之前的纯 JSON 字符串。"""

    task_id: str
    run_id: int | None = None
    buffer: list[str] = field(default_factory=list)  # 历史事件，供新连接回放
    queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)  # live tail；None=哨兵（done）
    done: bool = False
    error: str | None = None
    final_payload: str | None = None  # final 事件 JSON，mark_done 时投递
    bg_task: asyncio.Task | None = None
    readers: int = 0  # 当前有几个 SSE 连接在 tail（仅用于诊断/可可选清理）

    def attach_reader(self) -> None:
        self.readers += 1

    def detach_reader(self) -> None:
        self.readers = max(0, self.readers - 1)


_REGISTRY: dict[str, RunHandle] = {}


def get(task_id: str) -> RunHandle | None:
    return _REGISTRY.get(task_id)


def get_or_register(task_id: str) -> RunHandle:
    handle = _REGISTRY.get(task_id)
    if handle is None:
        handle = RunHandle(task_id=task_id)
        _REGISTRY[task_id] = handle
    return handle


def set_run_id(handle: RunHandle, run_id: int) -> None:
    handle.run_id = run_id


def publish(handle: RunHandle, payload_str: str) -> None:
    """后台 runner 调用：append 历史 + 投递 live queue。"""
    handle.buffer.append(payload_str)
    # put_nowait：读者若已断只是无人取，队列会留到下个读者或 drop 时清理；容量给足
    try:
        handle.queue.put_nowait(payload_str)
    except asyncio.QueueFull:  # 极端：读者卡死 + 队列满；丢最旧以保 live
        try:
            handle.queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            handle.queue.put_nowait(payload_str)
        except asyncio.QueueFull:
            logger.warning("run_registry_queue_full", task_id=handle.task_id)


def mark_done(handle: RunHandle, final_payload: str | None, error: str | None = None) -> None:
    """后台 runner 结束时调用：置 done + 投递 final + 哨兵。"""
    if handle.done:
        return
    handle.done = True
    handle.error = error
    handle.final_payload = final_payload
    if final_payload is not None:
        handle.buffer.append(final_payload)
        try:
            handle.queue.put_nowait(final_payload)
        except asyncio.QueueFull:
            pass
    # 哨兵通知所有 tail 读者退出 get() 循环
    try:
        handle.queue.put_nowait(None)
    except asyncio.QueueFull:
        pass


def cancel(task_id: str) -> bool:
    """前端 Stop：取消后台 asyncio.Task → astream 抛 CancelledError → runner catch 标 error。"""
    handle = _REGISTRY.get(task_id)
    if handle is None or handle.done:
        return False
    if handle.bg_task is not None and not handle.bg_task.done():
        handle.bg_task.cancel()
        return True
    return False


def drop(task_id: str) -> None:
    """从注册表移除（done 之后允许；由 resume/runner 末尾调用，避免内存泄漏）。"""
    _REGISTRY.pop(task_id, None)


def all_handles() -> dict[str, RunHandle]:
    """诊断用。"""
    return dict(_REGISTRY)


__all__: list[Any] = [
    "RunHandle",
    "get",
    "get_or_register",
    "set_run_id",
    "publish",
    "mark_done",
    "cancel",
    "drop",
]
