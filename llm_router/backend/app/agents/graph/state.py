"""Serializable platform state exchanged with the single DSH coordinator.

Database sessions, authenticated principals and provider secrets are never
included; they remain in the short-lived server-side run registry.
"""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    """单次智能体执行在平台准备、DSH 协调和持久化阶段间流转的状态。"""

    # ── 标识 ──
    agent_id: str
    org_id: str
    session_id: str
    run_id: int | None  # AgentRun.id，启动时创建、收口节点更新
    run_started_monotonic: float  # 仅进程内使用，用于落库真实运行耗时
    # general 模式（终端通用智能体）专用标识
    mode: str  # "agent"（管理端 playground）/ "general"（终端）
    task_id: str | None
    user_id: str | None
    department_id: str | None
    team_id: str | None
    exec_mode: str  # "craft"（自主执行）/ "ask"（只读问答）/ "plan"（出方案不执行）
    # general 模式：可选引用一个 Agent 行作「场景模板」，其 system_prompt 作为
    # persona/policy 前缀拼到 GENERAL_SYSTEM_PROMPT 之前（load_config 解析填充 base_prompt）。
    template_agent_id: str | None
    application_id: str | None
    page_context: dict

    # ── Agent 配置（load_config 节点填充）──
    system_prompt: str
    model_alias: str
    memory_config: dict
    judge_config: dict
    judge_template_id: str | None
    skill_ids: list[str]
    # 当前用户本轮可用的 Skill 精简目录；顺序为：明确调用、智能体默认、其他有权 Skill。
    skill_catalog: list[dict]
    # 智能体固定配置中的默认推荐 Skill（不构成排他白名单）。
    default_skills: list[dict]
    # 用户本轮通过选择器或唯一 /slug 明确调用的 Skill 快照。
    invoked_skill_ids: list[str]
    invoked_skills: list[dict]
    skill_slug_ambiguities: list[str]
    # 本轮模型实际载入说明与实际执行脚本/API 的记录，随 assistant 消息 metadata 持久化。
    loaded_skills: list[dict]
    executed_skills: list[dict]
    temperature: float | None
    max_tokens: int | None
    workspace_id: str | None
    rag_collection_id: str | None
    # general 模式多资源装配（空数组 = 按用户权限自动匹配全集，由 load_config 解析填充）
    ontology_ids: list[str]
    rag_collection_ids: list[str]
    # general 模式：当前轮明确调用的技能（结构化 UUID 优先，唯一 /slug 兼容）。
    referenced_skills: list[dict]
    # general 模式：用户在消息中以 @<file_id> 引用的工作空间文件 id（load_config 解析填充）。
    # DSH turn preparation reads these references; binary files are never inlined as text.
    referenced_file_ids: list[str]
    # 本轮结构化附件的服务端校验快照；写入 user TaskMessage.metadata 供历史回放。
    attachment_files: list[dict]
    # Effective roles/workspace capabilities contain no file names or content.
    effective_access: dict
    # Server-resolved per-turn scope. Personal is always present; shared
    # workspaces appear only after explicit natural-language or @file targeting.
    workspace_intent: dict

    # ── 对话 ──
    request: str  # 本轮用户输入
    messages: list[dict]  # OpenAI 风格消息序列（含历史 + 本轮）
    rag_context: list[dict]  # 检索命中的文本块
    memory_context: list[dict]  # 4 级长期记忆条目（general 模式 load_memory 填充）
    assistant_final: str  # 最终回复文本

    # ── 执行轨迹与用量 ──
    steps: list[dict]  # 逐步轨迹（llm 调用、工具调用、rag 命中等）
    usage: dict  # {"input_tokens": int, "output_tokens": int}
    tool_results: list[dict]
    # 五类资源调用痕迹（skill/ontology/rag/memory/data_interface），按执行顺序追加；
    # 经 stream_writer 下发 ``trace`` 事件实时展示，并随 save_memory 落 assistant
    # TaskMessage.metadata_ 供历史回放还原。技能仅在此落库、不重复发 trace 事件。
    traces: list[dict]
    # DSH bridge retry guard. The platform permits one retry for an identical
    # failing call, then forces the model to choose a fallback path.
    _dsh_last_failed_tool_fingerprint: str
    _dsh_consecutive_tool_failures: int

    # ── 判官 ──
    judge_result: dict | None

    # ── 错误 ──
    error: str | None
