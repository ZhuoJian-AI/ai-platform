"""AgentState —— LangGraph 智能体运行时可序列化状态 schema。

与 ProxyState 同约定：所有字段可序列化（str/int/bool/dict/list/None），状态在每个
super-step 后被 checkpointer 存储。非序列化运行时句柄（db session、admin）绝不入 state，
经 LangGraph ``context`` 注入（见 :mod:`app.operators.graph.context`）。密钥不入 state：
LLM 调用在 llm_client 内按 provider 解密、就地使用。
"""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    """单次智能体执行在图节点间流转的状态。"""

    # ── 标识 ──
    agent_id: str
    org_id: str
    session_id: str
    run_id: int | None  # AgentRun.id，启动时创建、收口节点更新
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

    # ── Agent 配置（load_config 节点填充）──
    system_prompt: str
    model_alias: str
    memory_config: dict
    judge_config: dict
    judge_template_id: str | None
    skill_ids: list[str]
    temperature: float | None
    max_tokens: int | None
    workspace_id: str | None
    rag_collection_id: str | None
    # general 模式多资源装配（空数组 = 按用户权限自动匹配全集，由 load_config 解析填充）
    ontology_ids: list[str]
    rag_collection_ids: list[str]
    # general 模式：用户在消息中以 /slug 引用的技能（load_config 解析填充，[{name,slug}]）。
    # agent_loop 据此注入「主动调用」指令——技能本身仍按用户权限全量装载为可调用工具。
    referenced_skills: list[dict]
    # general 模式：用户在消息中以 @<file_id> 引用的工作空间文件 id（load_config 解析填充）。
    # agent_loop 读取这些文件内容注入 system prompt（仿本体/RAG），二进制文件只标注不内联。
    referenced_file_ids: list[str]
    # 本轮结构化附件的服务端校验快照；写入 user TaskMessage.metadata 供历史回放。
    attachment_files: list[dict]

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

    # ── 判官 ──
    judge_result: dict | None

    # ── 错误 ──
    error: str | None
