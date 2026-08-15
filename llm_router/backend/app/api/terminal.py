"""Terminal API — 组织终端用户端（通用智能体AgileBuddy）。

全部由 ``require_user`` 守卫；任务仅属主可访问；工作空间文件读写受 scope 可见性约束。
通用智能体执行复用编译图 ``get_agent_graph()`` 的 general 模式分支。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_agent_graph, run_general_agent, stream_general_agent
from app.agents.graph import run_registry
from app.agents.graph.runner import stream_persisted_run
from app.auth.user_auth import CurrentUser, assert_user_org_access, assert_user_write, require_user
from app.database import get_db
from app.models.agent import Agent
from app.models.agent_run import AgentRun
from app.models.department import Department
from app.models.organization import Organization
from app.models.ontology import OntologyFile, OntologyFolder
from app.models.rag import RagCollection, RagDocument, RagFolder
from app.models.skill import SkillFile, SkillFolder
from app.models.task import Task
from app.models.team import Team
from app.schemas.rag import (
    RagCollectionCreate,
    RagCollectionRead,
    RagCollectionUpdate,
    RagChunkRead,
    RagDocumentCreate,
    RagDocumentRead,
    RagDocumentStatusRead,
    RagDocumentUpdate,
    RagFolderCreate,
    RagFolderRead,
    RagFolderUpdate,
    RagReingestRequest,
)
from app.schemas.data_interface import DataInterfaceRead, DataSystemRead
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate
from app.services.data_interface_service import (
    get_system,
    list_interfaces,
    list_systems,
)
from app.schemas.task import (
    TaskCreate,
    TaskRead,
    TaskReadWithMessages,
    TaskRunRequest,
    TaskUpdate,
)
from app.schemas.skill import (
    SkillFileCreate,
    SkillFileRead,
    SkillFileReadMeta,
    SkillFolderCreate,
    SkillFolderRead,
    SkillFolderUpdate,
)
from app.schemas.ontology import (
    OntologyFileCreate,
    OntologyFileRead,
    OntologyFileUpdate,
    OntologyFolderCreate,
    OntologyFolderRead,
    OntologyFolderRename,
)
from app.schemas.user import UserRead
from app.schemas.workspace import (
    WorkspaceFileCreate,
    WorkspaceFilePreviewRead,
    WorkspaceFileRead,
    WorkspaceFolderCreate,
    WorkspaceFolderRead,
    WorkspaceRead,
)
from app.services import memory_service, scope_service, task_service, workspace_service
from app.services import doc_parser, rag_service
from app.services import skills_pack_service
from app.services.skill_store_service import (
    create_folder as create_skill_folder,
    get_file as get_skill_file,
    get_folder as get_skill_folder,
    list_files as list_skill_files,
    list_folders as list_skill_folders,
    soft_delete_file as soft_delete_skill_file,
    soft_delete_folder as soft_delete_skill_folder,
    update_folder as update_skill_folder,
    upsert_file as upsert_skill_file,
)
from app.services.ontology_store_service import (
    create_folder as create_ontology_folder,
    get_file as get_ontology_file,
    get_folder as get_ontology_folder,
    list_files as list_ontology_files,
    list_folders as list_ontology_folders,
    rename_folder as rename_ontology_folder,
    soft_delete_file as soft_delete_ontology_file,
    soft_delete_folder as soft_delete_ontology_folder,
    update_file as update_ontology_file,
    upsert_file as upsert_ontology_file,
)
from app.services.agent_service import (
    create_agent as create_agent_svc,
    get_agent as get_agent_svc,
    list_agents as list_agents_svc,
    soft_delete_agent as soft_delete_agent_svc,
)

router = APIRouter()


async def _get_owned_task(db: AsyncSession, task_id: UUID, cu: CurrentUser) -> Task:
    task = await task_service.get_task(db, task_id)
    if task is None or str(task.user_id) != cu.id:
        raise HTTPException(status_code=404, detail="Task not found")
    assert_user_org_access(cu, task.organization_id)
    return task


async def _user_defaults(db: AsyncSession, cu: CurrentUser) -> dict:
    """终端默认装配：默认工作空间=用户个人工作空间；默认模型=最近一次执行任务时选中的模型
    （从未执行过任务则为 None——不预填，强制用户显式选择；选中并执行后写入 task.config 即成为默认）。
    last-used 必须仍在用户当前可用模型内，否则视为历史脏值（如已失效的裸 "glm"）置空，强制重新选择。"""
    ws = await scope_service.get_user_workspace(db, cu)
    workspace_id = str(ws.id) if ws else None
    model_alias = await task_service.get_last_used_model_alias(db, cu.id)
    if model_alias:
        models = await scope_service.list_available_models_for_user(db, cu)
        if model_alias not in models:
            model_alias = None
    return {"workspace_id": workspace_id, "model_alias": model_alias}


# ── 用户与资源 ──

@router.get("/terminal/me")
async def me_endpoint(cu: CurrentUser = Depends(require_user)):
    """当前终端用户档案 + 作用域。"""
    return {
        "user": UserRead.model_validate(cu.user).model_dump(),
        "department_id": cu.department_id,
        "team_id": cu.team_id,
        "scopes": scope_service.effective_scope_set(cu),
    }


@router.get("/terminal/resources")
async def resources_endpoint(
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """用户有效 scope 内的全部资源（供下拉与「全部自动匹配」预览）。"""
    workspaces = await scope_service.list_workspaces_for_user(db, cu)
    skills = await scope_service.list_skills_for_user(db, cu)
    ontologies = await scope_service.list_ontologies_for_user(db, cu)
    rags = await scope_service.list_rags_for_user(db, cu)
    defaults = await _user_defaults(db, cu)
    return {
        "workspaces": [WorkspaceRead.model_validate(w).model_dump() for w in workspaces],
        "skills": [{"id": str(s.id), "name": s.name, "slug": s.slug} for s in skills],
        # 本体已文件化：返回轻量摘要（id / name=文件名 / path），供下拉与计数。
        "ontologies": [
            {"id": str(o.id), "name": o.path.rsplit("/", 1)[-1], "path": o.path}
            for o in ontologies
        ],
        "rags": [RagCollectionRead.model_validate(r).model_dump() for r in rags],
        "defaults": defaults,
    }


@router.post("/terminal/skills-pack/export")
async def export_skills_pack_endpoint(
    request: Request,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """即时生成归口用户 skills 包 zip 并下载。

    鉴权内嵌 + 即时轮换：撤销该用户上一份 skills-pack key、即时签发新 scoped key，
    明文嵌入 zip 内 ``.mcp.json``（仅此一次返回）。第三方终端解压即可识别，无需再输凭证。
    """
    zip_bytes, filename = await skills_pack_service.build_skills_pack_zip(db, cu, request)
    await db.commit()
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/terminal/workspace-files")
async def list_all_ws_files_endpoint(
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """用户可访问的全部工作空间（组织/部门/团队/个人）内的文件轻量摘要。

    供任务输入框 @ 引用下拉：遍历用户有效 scope 内的工作空间，逐个列出文件，拼装
    {id, workspace_id, workspace_name, path, scope_type, is_binary}（不含 content）。
    """
    workspaces = await scope_service.list_workspaces_for_user(db, cu)
    out: list[dict] = []
    for ws in workspaces:
        files = await workspace_service.list_files(db, ws.id)
        for f in files:
            out.append({
                "id": str(f.id),
                "workspace_id": str(ws.id),
                "workspace_name": ws.name,
                "path": f.path,
                "scope_type": ws.scope_type,
                "is_binary": bool((f.metadata_ or {}).get("binary")),
            })
    out.sort(key=lambda x: x["path"])
    return out


@router.get("/terminal/models")
async def models_endpoint(
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """该用户可用的真实模型 id（按可访问的全部 API Key 聚合，embedding 模型已过滤）。

    ``model_alias`` 字段直接填这些模型 id 之一即可（或 "default" 走组织默认路由）。
    """
    models = await scope_service.list_available_models_for_user(db, cu)
    return {"models": models}


@router.get("/terminal/agents")
async def agents_endpoint(
    scope_type: str | None = Query(default=None, description="可选：按 scope 精确过滤"),
    scope_id: str | None = Query(default=None),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """用户可见的活跃智能体（组织级 + 用户 dept/team/user 命中），供终端「选智能体」下拉与智能体管理页。

    选中后以 ``template_agent_id`` 逐次覆盖运行（不落库）；选「不绑定」走通用智能体。
    不传 scope → 返回用户有效集合内全部可见智能体；传 scope → 必须在用户有效集合内（404）后精确过滤。
    返回完整字段（AgentRead），供终端智能体管理页编辑/创建。
    """
    if scope_type:
        if not _scope_in_effective(cu, scope_type, scope_id):
            raise HTTPException(status_code=404, detail="Scope not accessible")
        rows = await list_agents_svc(db, cu.organization_id, scope_type, scope_id)
    else:
        rows = await scope_service.list_agents_for_user(db, cu)
    return {"agents": [AgentRead.model_validate(a).model_dump(mode="json") for a in rows]}


@router.post("/terminal/agents", response_model=AgentRead, status_code=201)
async def create_agent_endpoint(
    data: AgentCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """新建智能体（个人/团队/部门 scope）。后续仅创建者可改删。

    - 不允许 organization scope（终端用户不得建组织级智能体）；
    - scope 必须落在用户有效集合内，否则 403；
    - model_alias 必须在用户当前可用模型内（仿 run_task_endpoint）；
    - created_by 记为当前用户；slug 在同 scope 内重复 → 409。
    """
    assert_user_write(cu)
    if data.scope_type == "organization":
        raise HTTPException(status_code=400, detail="终端不支持在组织级创建智能体，请选择个人/团队/部门")
    if not _scope_in_effective(cu, data.scope_type, str(data.scope_id) if data.scope_id else None):
        raise HTTPException(status_code=403, detail="无权在该作用域下创建智能体")
    if data.model_alias != "default":
        _available = await scope_service.list_available_models_for_user(db, cu)
        if data.model_alias not in _available:
            raise HTTPException(status_code=400, detail="所选模型当前不可用，请重新选择模型")
    try:
        agent = await create_agent_svc(db, cu.organization_id, data, created_by=cu.id)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Slug already exists")
    await db.commit()
    await db.refresh(agent)
    return agent


@router.patch("/terminal/agents/{agent_id}", response_model=AgentRead)
async def update_agent_endpoint(
    agent_id: UUID, data: AgentUpdate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """编辑智能体（仅创建者）。终端不允许迁移 scope、改 created_by / organization_id。"""
    assert_user_write(cu)
    agent = await _get_visible_agent(db, agent_id, cu)
    _assert_owner(agent, cu)
    provided = data.model_dump(exclude_unset=True)
    for k in ("scope_type", "scope_id", "created_by", "organization_id"):
        provided.pop(k, None)
    if "model_alias" in provided and provided["model_alias"] != "default":
        _available = await scope_service.list_available_models_for_user(db, cu)
        if provided["model_alias"] not in _available:
            raise HTTPException(status_code=400, detail="所选模型当前不可用，请重新选择模型")
    for field, value in provided.items():
        setattr(agent, field, value)
    agent.version += 1
    await db.flush()
    await db.refresh(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/terminal/agents/{agent_id}", status_code=204)
async def delete_agent_endpoint(
    agent_id: UUID,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除智能体（仅创建者，软删）。"""
    assert_user_write(cu)
    agent = await _get_visible_agent(db, agent_id, cu)
    _assert_owner(agent, cu)
    await soft_delete_agent_svc(db, agent)
    await db.commit()


@router.get("/terminal/memory")
async def memory_endpoint(
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """用户可见的 4 级长期记忆（右侧面板预览）。"""
    scopes = scope_service.effective_scope_set(cu)
    rows = await memory_service.list_memory_for_user(db, cu.organization_id, scopes)
    return [
        {
            "id": str(m.id), "scope_type": m.scope_type,
            "scope_id": str(m.scope_id) if m.scope_id else None,
            "category": m.category, "content": m.content, "source": m.source,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


# ── 任务 ──

@router.post("/terminal/tasks", response_model=TaskRead, status_code=201)
async def create_task_endpoint(
    data: TaskCreate, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    # 未显式选择工作空间/模型时，填入用户默认（个人工作空间 + 最近一次使用的模型）。
    if data.config.workspace_id is None or data.config.model_alias is None:
        defaults = await _user_defaults(db, cu)
        if data.config.workspace_id is None:
            data.config.workspace_id = defaults["workspace_id"]
        if data.config.model_alias is None:
            data.config.model_alias = defaults["model_alias"]
    task = await task_service.create_task(
        db, org_id=cu.organization_id, user_id=cu.id,
        department_id=cu.department_id, team_id=cu.team_id, data=data,
    )
    await db.commit()
    return task


@router.get("/terminal/tasks", response_model=list[TaskRead])
async def list_tasks_endpoint(
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    tasks = await task_service.list_tasks(db, cu.id)
    return tasks


@router.get("/terminal/tasks/{task_id}", response_model=TaskReadWithMessages)
async def get_task_endpoint(
    task_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    task = await _get_owned_task(db, task_id, cu)
    data = TaskReadWithMessages.model_validate(task)
    # 该任务最新 run 状态：前端据此决定是否调 GET /stream 重连（detach 执行刷新不丢）。
    run_status = (await db.execute(
        select(AgentRun.status).where(AgentRun.task_id == str(task.id))
        .order_by(AgentRun.id.desc()).limit(1)
    )).scalar_one_or_none()
    data.run_status = run_status
    return data


@router.patch("/terminal/tasks/{task_id}", response_model=TaskRead)
async def update_task_endpoint(
    task_id: UUID, data: TaskUpdate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    task = await _get_owned_task(db, task_id, cu)
    await task_service.update_task(db, task, data)
    await db.commit()
    return task


@router.delete("/terminal/tasks/{task_id}", status_code=204)
async def delete_task_endpoint(
    task_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    task = await _get_owned_task(db, task_id, cu)
    await task_service.soft_delete_task(db, task)
    await db.commit()


@router.delete("/terminal/tasks/{task_id}/messages/{message_id}", status_code=204)
async def delete_task_message_endpoint(
    task_id: UUID, message_id: UUID,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除任务中的一整轮对话（用户消息 + 紧随其后的 assistant 消息）。

    若该轮 assistant 调用了写文件工具（workspace_write_file / generate_docx），
    一并软删除仅本轮产出、且未被后续轮次覆盖的工作空间文件。
    """
    task = await _get_owned_task(db, task_id, cu)
    await task_service.soft_delete_task_turn(db, task, message_id)
    await db.commit()


@router.post("/terminal/tasks/{task_id}/run")
async def run_task_endpoint(
    task_id: UUID,
    data: TaskRunRequest,
    request: Request,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """运行通用智能体。stream=true 返回 SSE，否则返回最终结果。"""
    task = await _get_owned_task(db, task_id, cu)
    assert_user_write(cu)
    graph = get_agent_graph()
    # 旧任务 config 可能缺 workspace_id，运行时按用户默认补齐。
    # 模型必须显式选择（创建时未选且无最近使用默认则空）——不选模型不允许执行。
    cfg = dict(task.config or {})
    if not cfg.get("workspace_id"):
        defaults = await _user_defaults(db, cu)
        if defaults["workspace_id"]:
            cfg["workspace_id"] = defaults["workspace_id"]
    if not cfg.get("model_alias"):
        raise HTTPException(status_code=400, detail="请先选择模型后再执行任务")
    # 模型必须在用户当前可用范围内（脏值如裸 "glm" 或已失效模型直接挡掉，避免跑到路由失败）。
    _available = await scope_service.list_available_models_for_user(db, cu)
    if cfg["model_alias"] != "default" and cfg["model_alias"] not in _available:
        raise HTTPException(status_code=400, detail="所选模型当前不可用，请重新选择模型")
    # 逐次运行覆盖智能体（不落库）：
    #   字段未传 → 沿用 task.config.template_agent_id（向后兼容 demo 旧 /run 调用）
    #   显式传（UUID 或 null/空）→ 覆盖：UUID 用此智能体，null 强制通用智能体。
    provided = data.model_dump(exclude_unset=True)
    if "template_agent_id" in provided:
        tpl = provided["template_agent_id"]
        cfg["template_agent_id"] = (tpl or None)
    if data.stream:
        resp = await stream_general_agent(
            graph, org_id=str(task.organization_id), user=cu, task=task,
            message=data.message, config=cfg,
            session_id=task.session_id, db=db, request=request,
        )
        # 流式响应内部完成图执行（含 save_memory/extract_memory/write_run_log）；
        # commit 由各节点 flush 后于响应结束时统一提交。
        return resp

    result = await run_general_agent(
        graph, org_id=str(task.organization_id), user=cu, task=task,
        message=data.message, config=cfg,
        session_id=task.session_id, db=db, request=request,
    )
    await db.commit()
    return result


@router.get("/terminal/tasks/{task_id}/stream")
async def stream_task_endpoint(
    task_id: UUID,
    request: Request,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """resume 端点：重连/回放一个 run 的 SSE。

    三种情形：
    1. registry 有 active handle（同进程内 run 仍在跑）→ 回放 buffer + 续接 live queue；
    2. 最新 run 状态 success/error（已完成）→ 从 agent_run_events 回放已落库事件；
    3. 最新 run 状态 running 但无 live handle（进程重启孤儿）→ 标 interrupted + 回放 + 合成 final。
    无 run → 404。
    """
    task = await _get_owned_task(db, task_id, cu)
    task_id_str = str(task.id)

    # 情形 1：live handle
    handle = run_registry.get(task_id_str)
    if handle is not None and not handle.done:
        from app.agents.graph.runner import _sse_replay_and_tail
        return StreamingResponse(
            _sse_replay_and_tail(handle),
            status_code=200, media_type="text/event-stream",
            headers={"cache-control": "no-cache", "connection": "keep-alive", "x-accel-buffering": "no"},
        )

    # 最新 run（按 id desc）
    run = (await db.execute(
        select(AgentRun).where(AgentRun.task_id == task_id_str).order_by(AgentRun.id.desc()).limit(1)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="该任务尚无执行记录")

    if run.status == "running":
        # 情形 3：孤儿 run（进程重启后内存 handle 已失）→ 标 interrupted + 回放 + 合成 final
        run.status = "error"
        run.error = "interrupted by server restart"
        await db.commit()
        return await stream_persisted_run(db, run.id, interrupted=True)

    # 情形 2：已完成 → 纯回放
    return await stream_persisted_run(db, run.id, interrupted=False)


@router.post("/terminal/tasks/{task_id}/cancel")
async def cancel_task_endpoint(
    task_id: UUID,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """取消运行中的 run：registry.cancel 触发后台 asyncio.Task.cancel → astream 抛 CancelledError → runner 标 error。"""
    task = await _get_owned_task(db, task_id, cu)
    cancelled = run_registry.cancel(str(task.id))
    return {"cancelled": cancelled}


# ── 工作空间文件（用户 scope 内）──

async def _get_visible_workspace(db: AsyncSession, ws_id: UUID, cu: CurrentUser):
    ws = await workspace_service.get_workspace(db, ws_id)
    if ws is None or not scope_service.is_workspace_visible(ws, cu):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.get("/terminal/workspaces/{ws_id}/files", response_model=list[WorkspaceFileRead])
async def list_ws_files_endpoint(
    ws_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    ws = await _get_visible_workspace(db, ws_id, cu)
    return await workspace_service.list_files(db, ws.id)


@router.post("/terminal/workspaces/{ws_id}/files", response_model=WorkspaceFileRead, status_code=201)
async def upsert_ws_file_endpoint(
    ws_id: UUID, data: WorkspaceFileCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    assert_user_write(cu)
    ws = await _get_visible_workspace(db, ws_id, cu)
    f = await workspace_service.upsert_file(db, ws, data)
    await db.commit()
    return f


@router.post("/terminal/workspaces/{ws_id}/files/upload", response_model=WorkspaceFileRead, status_code=201)
async def upload_ws_file_endpoint(
    ws_id: UUID,
    file: UploadFile = File(...),
    path: str | None = Form(default=None),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    assert_user_write(cu)
    ws = await _get_visible_workspace(db, ws_id, cu)
    raw = await file.read()
    try:
        f = await workspace_service.ingest_uploaded_file(
            db, ws, path=path or file.filename or "upload.bin",
            filename=file.filename or "upload.bin", content_type=file.content_type, raw=raw,
        )
    except workspace_service.WorkspaceFileUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return f


@router.get("/terminal/files/{file_id}", response_model=WorkspaceFileRead)
async def get_ws_file_endpoint(
    file_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    f = await workspace_service.get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await workspace_service.get_workspace(db, f.workspace_id)
    if ws is None or not scope_service.is_workspace_visible(ws, cu):
        raise HTTPException(status_code=404, detail="File not found")
    return f


@router.get("/terminal/files/{file_id}/preview", response_model=WorkspaceFilePreviewRead)
async def preview_ws_file_endpoint(
    file_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    f = await workspace_service.get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await workspace_service.get_workspace(db, f.workspace_id)
    if ws is None or not scope_service.is_workspace_visible(ws, cu):
        raise HTTPException(status_code=404, detail="File not found")
    return f


@router.post("/terminal/files/{file_id}/reparse", response_model=WorkspaceFileRead)
async def reparse_ws_file_endpoint(
    file_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    assert_user_write(cu)
    f = await workspace_service.get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await workspace_service.get_workspace(db, f.workspace_id)
    if ws is None or not scope_service.is_workspace_visible(ws, cu):
        raise HTTPException(status_code=404, detail="File not found")
    f = await workspace_service.reparse_file(db, f)
    await db.commit()
    return f


# 免登录公开访问的 HTML 类扩展名（content 为 HTML，浏览器可直接渲染）。
PUBLIC_HTML_EXTS = {"html", "htm", "doc", "docx"}


@router.get("/terminal/public/files/{file_id}")
async def public_ws_file_endpoint(file_id: UUID, db: AsyncSession = Depends(get_db)):
    """免登录永久公开访问工作空间 HTML 文件（分享链接）。

    仅放行 HTML 类扩展名（html/htm/doc/docx，内容为 HTML），其余一律 404——
    即「分享」只对 HTML 文件生效。``file_id`` 为 UUID，链接永久有效，持有者均可访问。
    """
    f = await workspace_service.get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ext = f.path.rsplit(".", 1)[-1].lower() if "." in f.path else ""
    if ext not in PUBLIC_HTML_EXTS:
        raise HTTPException(status_code=404, detail="File not found")
    content = workspace_service.resolve_file_content(f)
    return Response(content=content, media_type="text/html; charset=utf-8")


@router.patch("/terminal/files/{file_id}", response_model=WorkspaceFileRead)
async def update_ws_file_endpoint(
    file_id: UUID, data: WorkspaceFileCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    assert_user_write(cu)
    f = await workspace_service.get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await workspace_service.get_workspace(db, f.workspace_id)
    if ws is None or not scope_service.is_workspace_visible(ws, cu):
        raise HTTPException(status_code=404, detail="File not found")
    updated = await workspace_service.upsert_file(db, ws, data)
    await db.commit()
    return updated


@router.delete("/terminal/files/{file_id}", status_code=204)
async def delete_ws_file_endpoint(
    file_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    assert_user_write(cu)
    f = await workspace_service.get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await workspace_service.get_workspace(db, f.workspace_id)
    if ws is None or not scope_service.is_workspace_visible(ws, cu):
        raise HTTPException(status_code=404, detail="File not found")
    await workspace_service.soft_delete_file(db, f)
    await db.commit()


# ── 工作空间文件夹（用户 scope 内）──

@router.get("/terminal/workspaces/{ws_id}/folders", response_model=list[WorkspaceFolderRead])
async def list_ws_folders_endpoint(
    ws_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    ws = await _get_visible_workspace(db, ws_id, cu)
    return await workspace_service.list_folders(db, ws.id)


@router.post("/terminal/workspaces/{ws_id}/folders", response_model=WorkspaceFolderRead, status_code=201)
async def create_ws_folder_endpoint(
    ws_id: UUID, data: WorkspaceFolderCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    assert_user_write(cu)
    ws = await _get_visible_workspace(db, ws_id, cu)
    folder = await workspace_service.create_folder(db, ws, data)
    await db.commit()
    return folder


@router.delete("/terminal/folders/{folder_id}", status_code=204)
async def delete_ws_folder_endpoint(
    folder_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    assert_user_write(cu)
    folder = await workspace_service.get_folder(db, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    ws = await workspace_service.get_workspace(db, folder.workspace_id)
    if ws is None or not scope_service.is_workspace_visible(ws, cu):
        raise HTTPException(status_code=404, detail="Folder not found")
    await workspace_service.soft_delete_folder(db, folder)
    await db.commit()


# ── 知识库（RAG）：用户 scope 内可见；删除/重命名/编辑仅限自己创建 ──

def _scope_in_effective(cu: CurrentUser, scope_type: str, scope_id: str | None) -> bool:
    """选中 scope 是否落在用户有效 scope 集合内（组织/部门/团队/个人）。"""
    for t, sid in scope_service.effective_scope_set(cu):
        if t == scope_type and (sid or None) == (scope_id or None):
            return True
    return False


async def _get_visible_collection(db: AsyncSession, coll_id: UUID, cu: CurrentUser) -> RagCollection:
    """取知识库并校验可见（同组织 + scope 命中用户有效集合）；不可见一律 404。"""
    coll = await rag_service.get_collection(db, coll_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_user_org_access(cu, coll.organization_id)
    if not _scope_in_effective(cu, coll.scope_type, coll.scope_id):
        raise HTTPException(status_code=404, detail="RAG collection not found")
    return coll


async def _get_visible_system(db: AsyncSession, system_id: UUID, cu: CurrentUser):
    """取数据系统并校验可见（同组织 + scope 命中用户有效集合）；不可见一律 404。"""
    s = await get_system(db, system_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_user_org_access(cu, s.organization_id)
    if not _scope_in_effective(cu, s.scope_type, s.scope_id):
        raise HTTPException(status_code=404, detail="Data system not found")
    return s


def _assert_owner(
    entity: RagCollection | RagDocument | RagFolder | SkillFolder | OntologyFolder | OntologyFile | Agent,
    cu: CurrentUser,
) -> None:
    """断言当前用户为该资源的创建者；否则 403。

    admin / 历史数据 created_by 为 None，终端用户均不得删除/重命名/编辑。
    """
    if not entity.created_by or entity.created_by != cu.id:
        raise HTTPException(status_code=403, detail="只能操作自己创建的资源")


async def _get_visible_agent(db: AsyncSession, agent_id: UUID, cu: CurrentUser) -> Agent:
    """取智能体并校验可见（同组织 + scope 命中用户有效集合）；不可见一律 404。"""
    a = await get_agent_svc(db, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    assert_user_org_access(cu, a.organization_id)
    if not _scope_in_effective(cu, a.scope_type, a.scope_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return a


async def _get_visible_skill_folder(db: AsyncSession, folder_id: UUID, cu: CurrentUser) -> SkillFolder:
    """取技能文件夹并校验可见（同组织 + scope 命中用户有效集合）；不可见一律 404。"""
    f = await get_skill_folder(db, folder_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Skill folder not found")
    assert_user_org_access(cu, f.organization_id)
    if not _scope_in_effective(cu, f.scope_type, f.scope_id):
        raise HTTPException(status_code=404, detail="Skill folder not found")
    return f


@router.get("/terminal/kb-nodes")
async def kb_nodes_endpoint(
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """用户可见的组织架构单链（组织→部门→团队→个人），供左栏树渲染。

    每级返回 ``{scope_type, scope_id, name}``；部门/团队缺失则跳过该级。
    """
    nodes: list[dict] = []
    org = (await db.execute(
        select(Organization).where(
            Organization.id == cu.organization_id, Organization.deleted_at.is_(None)
        )
    )).scalar_one_or_none()
    nodes.append({"scope_type": "organization", "scope_id": None, "name": org.name if org else "组织"})

    if cu.department_id:
        dept = (await db.execute(
            select(Department).where(
                Department.id == cu.department_id, Department.deleted_at.is_(None)
            )
        )).scalar_one_or_none()
        if dept:
            nodes.append({"scope_type": "department", "scope_id": dept.id, "name": dept.name})
    if cu.team_id:
        team = (await db.execute(
            select(Team).where(Team.id == cu.team_id, Team.deleted_at.is_(None))
        )).scalar_one_or_none()
        if team:
            nodes.append({"scope_type": "team", "scope_id": team.id, "name": team.name})
    # 个人级：display_name 优先，回退 username
    user_name = cu.user.display_name or cu.user.username
    nodes.append({"scope_type": "user", "scope_id": cu.id, "name": user_name})
    return nodes


@router.get("/terminal/data-systems", response_model=list[DataSystemRead])
async def list_data_systems_endpoint(
    scope_type: str = Query(..., description="organization/department/team/user"),
    scope_id: str | None = Query(default=None),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """列出选中 scope 下的数据系统（scope 必须在用户有效集合内）；终端只读。"""
    if not _scope_in_effective(cu, scope_type, scope_id):
        raise HTTPException(status_code=404, detail="Scope not accessible")
    return await list_systems(db, cu.organization_id, scope_type=scope_type, scope_id=scope_id)


@router.get(
    "/terminal/data-systems/{system_id}/data-interfaces",
    response_model=list[DataInterfaceRead],
)
async def list_data_interfaces_endpoint(
    system_id: UUID,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """列出可见数据系统下的数据接口（输入/输出样例）；终端只读。"""
    s = await _get_visible_system(db, system_id, cu)
    return await list_interfaces(db, s.id)


@router.get("/terminal/rag", response_model=list[RagCollectionRead])
async def list_kb_collections_endpoint(
    scope_type: str = Query(..., description="organization/department/team/user"),
    scope_id: str | None = Query(default=None),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """列出选中 scope 下的知识库（scope 必须在用户有效集合内）。"""
    if not _scope_in_effective(cu, scope_type, scope_id):
        raise HTTPException(status_code=404, detail="Scope not accessible")
    return await rag_service.list_collections(
        db, cu.organization_id, scope_type=scope_type, scope_id=scope_id,
    )


@router.post("/terminal/rag", response_model=RagCollectionRead, status_code=201)
async def create_kb_collection_endpoint(
    data: RagCollectionCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """新建知识库。scope 必须在用户有效集合内；created_by 记为当前用户；
    嵌入参数取组织级默认。"""
    assert_user_write(cu)
    if not _scope_in_effective(cu, data.scope_type, data.scope_id):
        raise HTTPException(status_code=403, detail="无权在该作用域下新建知识库")
    ingest_cfg = await rag_service.get_ingest_config(db, cu.organization_id)
    data.embedding_model = ingest_cfg.embedding_model
    data.embedding_dim = ingest_cfg.embedding_dim
    try:
        coll = await rag_service.create_collection(db, cu.organization_id, data, created_by=cu.id)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Slug already exists")
    await db.commit()
    await db.refresh(coll)
    return coll


@router.patch("/terminal/rag/{coll_id}", response_model=RagCollectionRead)
async def update_kb_collection_endpoint(
    coll_id: UUID, data: RagCollectionUpdate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """重命名知识库（仅创建者）。"""
    assert_user_write(cu)
    coll = await _get_visible_collection(db, coll_id, cu)
    _assert_owner(coll, cu)
    # 终端不允许改 scope，仅 name/description/chunk 参数
    data.scope_type = None
    data.scope_id = None
    coll = await rag_service.update_collection(db, coll, data)
    await db.commit()
    await db.refresh(coll)
    return coll


@router.delete("/terminal/rag/{coll_id}", status_code=204)
async def delete_kb_collection_endpoint(
    coll_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除知识库（仅创建者）。"""
    assert_user_write(cu)
    coll = await _get_visible_collection(db, coll_id, cu)
    _assert_owner(coll, cu)
    await rag_service.soft_delete_collection(db, coll)
    await db.commit()


@router.get("/terminal/rag/{coll_id}/folders", response_model=list[RagFolderRead])
async def list_kb_folders_endpoint(
    coll_id: UUID,
    parent: str | None = Query(default=None, description="仅返回该文件夹直接子文件夹；空串=根"),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    coll = await _get_visible_collection(db, coll_id, cu)
    return await rag_service.list_folders(db, coll.id, parent=parent)


@router.post("/terminal/rag/{coll_id}/folders", response_model=RagFolderRead, status_code=201)
async def create_kb_folder_endpoint(
    coll_id: UUID, data: RagFolderCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """新建文件夹（可在任意可见知识库下；created_by 记为当前用户）。"""
    assert_user_write(cu)
    coll = await _get_visible_collection(db, coll_id, cu)
    folder = await rag_service.create_folder(db, coll, data, created_by=cu.id)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.patch("/terminal/rag/folders/{folder_id}", response_model=RagFolderRead)
async def rename_kb_folder_endpoint(
    folder_id: UUID, data: RagFolderUpdate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """重命名文件夹（仅创建者）。"""
    assert_user_write(cu)
    folder = await rag_service.get_folder(db, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="RAG folder not found")
    coll = await _get_visible_collection(db, folder.collection_id, cu)
    _assert_owner(folder, cu)
    try:
        folder = await rag_service.rename_folder(db, folder, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="目标路径已存在同名文件夹")
    await db.commit()
    await db.refresh(folder)
    _ = coll  # 可见性已校验
    return folder


@router.delete("/terminal/rag/folders/{folder_id}", status_code=204)
async def delete_kb_folder_endpoint(
    folder_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除文件夹及其下内容（仅创建者）。"""
    assert_user_write(cu)
    folder = await rag_service.get_folder(db, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="RAG folder not found")
    await _get_visible_collection(db, folder.collection_id, cu)
    _assert_owner(folder, cu)
    await rag_service.soft_delete_folder(db, folder)
    await db.commit()


@router.get("/terminal/rag/{coll_id}/documents", response_model=list[RagDocumentRead])
async def list_kb_documents_endpoint(
    coll_id: UUID,
    folder_path: str | None = Query(default=None, description="仅返回该文件夹直接下属文档；空串=根"),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    coll = await _get_visible_collection(db, coll_id, cu)
    return await rag_service.list_documents(db, coll.id, folder_path=folder_path)


@router.post("/terminal/rag/{coll_id}/documents", response_model=RagDocumentRead, status_code=201)
async def ingest_kb_document_endpoint(
    coll_id: UUID, data: RagDocumentCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """文档入库（可在任意可见知识库下；created_by 记为当前用户）。"""
    assert_user_write(cu)
    coll = await _get_visible_collection(db, coll_id, cu)
    try:
        doc = await rag_service.ingest_document(db, coll, coll.organization_id, data, created_by=cu.id)
    except rag_service.EmbeddingError as exc:
        # service 已置 doc=failed + flush；commit 落库 failed 供排查，转 502
        await db.commit()
        raise HTTPException(status_code=502, detail=f"文档入库失败：embedding 不可用 — {exc}") from exc
    await db.commit()
    await db.refresh(doc)
    return doc


@router.post("/terminal/rag/{coll_id}/documents/upload", response_model=RagDocumentRead, status_code=201)
async def upload_kb_document_endpoint(
    coll_id: UUID,
    file: UploadFile = File(..., description="待解析入库的 PDF / Word / Excel / PowerPoint / 文本文档"),
    title: str | None = Form(default=None),
    folder_path: str = Form(default=""),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """上传文件入库（与管理端一致）：请求内同步解析抽取文本并落库，分块+嵌入交后台任务
    异步进行。``created_by`` 记为当前用户；可在任意可见知识库下上传。返回 ``status='pending'``，
    前端轮询 ``GET /terminal/rag/documents/{id}/status`` 获取阶段化进度。
    """
    assert_user_write(cu)
    coll = await _get_visible_collection(db, coll_id, cu)
    raw = await file.read()
    try:
        return await rag_service.ingest_uploaded_file(
            db, coll, coll.organization_id,
            filename=file.filename or "upload.bin",
            content_type=file.content_type,
            raw=raw,
            title=title,
            folder_path=folder_path,
            created_by=cu.id,
        )
    except doc_parser.UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/terminal/rag/documents/{doc_id}/status", response_model=RagDocumentStatusRead)
async def kb_document_status_endpoint(
    doc_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """轮询文档解析入库状态（上传后前端按 ~1s 轮询至 ready/failed）。"""
    doc = await rag_service.get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    await _get_visible_collection(db, doc.collection_id, cu)
    status = await rag_service.get_document_status(db, doc.id)
    if status is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    return status


@router.patch("/terminal/rag/documents/{doc_id}", response_model=RagDocumentRead)
async def update_kb_document_endpoint(
    doc_id: UUID, data: RagDocumentUpdate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """重命名文档（仅创建者）。"""
    assert_user_write(cu)
    doc = await rag_service.get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    await _get_visible_collection(db, doc.collection_id, cu)
    _assert_owner(doc, cu)
    doc = await rag_service.update_document(db, doc, data)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/terminal/rag/documents/{doc_id}", status_code=204)
async def delete_kb_document_endpoint(
    doc_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除文档（仅创建者）。"""
    assert_user_write(cu)
    doc = await rag_service.get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    await _get_visible_collection(db, doc.collection_id, cu)
    _assert_owner(doc, cu)
    await rag_service.soft_delete_document(db, doc)
    await db.commit()


@router.get("/terminal/rag/documents/{doc_id}/chunks", response_model=list[RagChunkRead])
async def list_kb_chunks_endpoint(
    doc_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    doc = await rag_service.get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    await _get_visible_collection(db, doc.collection_id, cu)
    chunks = await rag_service.list_chunks(db, doc.id)
    return [
        RagChunkRead(
            id=c.id,
            document_id=c.document_id,
            content=c.content,
            chunk_index=c.metadata_.get("chunk_index", 0) if isinstance(c.metadata_, dict) else 0,
            has_embedding=c.embedding is not None,
        )
        for c in chunks
    ]


@router.post("/terminal/rag/documents/{doc_id}/reingest", response_model=RagDocumentRead)
async def reingest_kb_document_endpoint(
    doc_id: UUID, data: RagReingestRequest,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """重新入库（仅创建者）：``chunks`` 为分块列表时按编辑边界落库；为 null 时从原文重切。"""
    assert_user_write(cu)
    doc = await rag_service.get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    coll = await _get_visible_collection(db, doc.collection_id, cu)
    _assert_owner(doc, cu)
    try:
        doc = await rag_service.reingest_document(db, doc, coll.organization_id, data)
    except rag_service.EmbeddingError as exc:
        # 回滚：恢复旧分块与原 doc，不留下 0 chunk 的 failed 行
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"重新入库失败：embedding 不可用 — {exc}") from exc
    await db.commit()
    await db.refresh(doc)
    return doc


# ── 技能（SkillFolder）：用户 scope 内可见；删除/重命名/补传仅限自己创建 ──

@router.get("/terminal/skills", response_model=list[SkillFolderRead])
async def list_skills_endpoint(
    scope_type: str = Query(..., description="organization/department/team/user"),
    scope_id: str | None = Query(default=None),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """列出选中 scope 下的技能文件夹（scope 必须在用户有效集合内）。"""
    if not _scope_in_effective(cu, scope_type, scope_id):
        raise HTTPException(status_code=404, detail="Scope not accessible")
    return await list_skill_folders(db, cu.organization_id, scope_type, scope_id)


@router.post("/terminal/skills", response_model=SkillFolderRead, status_code=201)
async def create_skill_endpoint(
    data: SkillFolderCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """导入技能：新建技能文件夹（created_by 记为当前用户）；随后前端补传 skill.md。"""
    assert_user_write(cu)
    if not _scope_in_effective(cu, data.scope_type, data.scope_id):
        raise HTTPException(status_code=403, detail="无权在该作用域下新建技能")
    try:
        f = await create_skill_folder(db, cu.organization_id, data, created_by=cu.id)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists in this scope")
    await db.commit()
    await db.refresh(f)
    return f


@router.patch("/terminal/skills/{folder_id}", response_model=SkillFolderRead)
async def update_skill_endpoint(
    folder_id: UUID, data: SkillFolderUpdate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """重命名技能（仅创建者）；终端仅允许改 name。"""
    assert_user_write(cu)
    f = await _get_visible_skill_folder(db, folder_id, cu)
    _assert_owner(f, cu)
    if not data.name:
        raise HTTPException(status_code=400, detail="name required")
    f = await update_skill_folder(db, f, SkillFolderUpdate(name=data.name))
    await db.commit()
    await db.refresh(f)
    return f


@router.delete("/terminal/skills/{folder_id}", status_code=204)
async def delete_skill_endpoint(
    folder_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除技能（仅创建者）。"""
    assert_user_write(cu)
    f = await _get_visible_skill_folder(db, folder_id, cu)
    _assert_owner(f, cu)
    await soft_delete_skill_folder(db, f)
    await db.commit()


@router.get("/terminal/skills/{folder_id}/files", response_model=list[SkillFileReadMeta])
async def list_skill_files_endpoint(
    folder_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """列出技能文件夹内文件（scope 可见即可读）。"""
    f = await _get_visible_skill_folder(db, folder_id, cu)
    return await list_skill_files(db, f.id)


@router.post("/terminal/skills/{folder_id}/files", response_model=SkillFileRead, status_code=201)
async def upsert_skill_file_endpoint(
    folder_id: UUID, data: SkillFileCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """补传文件（仅技能创建者）。"""
    assert_user_write(cu)
    f = await _get_visible_skill_folder(db, folder_id, cu)
    _assert_owner(f, cu)
    fl = await upsert_skill_file(db, f, data)
    await db.commit()
    await db.refresh(fl)
    return fl


@router.get("/terminal/skill-files/{file_id}", response_model=SkillFileRead)
async def get_skill_file_endpoint(
    file_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """取技能文件内容（scope 可见即可读）。"""
    fl = await get_skill_file(db, file_id)
    if fl is None:
        raise HTTPException(status_code=404, detail="Skill file not found")
    await _get_visible_skill_folder(db, fl.skill_folder_id, cu)
    return fl


@router.delete("/terminal/skill-files/{file_id}", status_code=204)
async def delete_skill_file_endpoint(
    file_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除技能文件（仅技能创建者）。"""
    assert_user_write(cu)
    fl = await get_skill_file(db, file_id)
    if fl is None:
        raise HTTPException(status_code=404, detail="Skill file not found")
    f = await _get_visible_skill_folder(db, fl.skill_folder_id, cu)
    _assert_owner(f, cu)
    await soft_delete_skill_file(db, fl)
    await db.commit()



# ── 本体（OntologyFolder / OntologyFile）：用户 scope 内可见；删除/重命名/编辑仅限自己创建 ──


async def _get_visible_ontology_folder(db: AsyncSession, folder_id: UUID, cu: CurrentUser) -> OntologyFolder:
    """取本体文件夹并校验可见（同组织 + scope 命中用户有效集合）；不可见一律 404。"""
    f = await get_ontology_folder(db, folder_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Ontology folder not found")
    assert_user_org_access(cu, f.organization_id)
    if not _scope_in_effective(cu, f.scope_type, f.scope_id):
        raise HTTPException(status_code=404, detail="Ontology folder not found")
    return f


async def _get_visible_ontology_file(db: AsyncSession, file_id: UUID, cu: CurrentUser) -> OntologyFile:
    """取本体文件并校验可见（同组织 + scope 命中用户有效集合）；不可见一律 404。"""
    f = await get_ontology_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Ontology file not found")
    assert_user_org_access(cu, f.organization_id)
    if not _scope_in_effective(cu, f.scope_type, f.scope_id):
        raise HTTPException(status_code=404, detail="Ontology file not found")
    return f


@router.get("/terminal/ontology-folders", response_model=list[OntologyFolderRead])
async def list_ontology_folders_endpoint(
    scope_type: str = Query(..., description="organization/department/team/user"),
    scope_id: str | None = Query(default=None),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """列出选中 scope 下的本体文件夹（scope 必须在用户有效集合内）。"""
    if not _scope_in_effective(cu, scope_type, scope_id):
        raise HTTPException(status_code=404, detail="Scope not accessible")
    return await list_ontology_folders(db, cu.organization_id, scope_type, scope_id)


@router.post("/terminal/ontology-folders", response_model=OntologyFolderRead, status_code=201)
async def create_ontology_folder_endpoint(
    data: OntologyFolderCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """新建本体文件夹（created_by 记为当前用户）；scope 必须在用户有效集合内。"""
    assert_user_write(cu)
    if not _scope_in_effective(cu, data.scope_type, data.scope_id):
        raise HTTPException(status_code=403, detail="无权在该作用域下新建本体文件夹")
    f = await create_ontology_folder(
        db, cu.organization_id, data.scope_type, data.scope_id, data.path, created_by=cu.id,
    )
    await db.commit()
    await db.refresh(f)
    return f


@router.patch("/terminal/ontology-folders/{folder_id}", response_model=OntologyFolderRead)
async def rename_ontology_folder_endpoint(
    folder_id: UUID, data: OntologyFolderRename,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """重命名本体文件夹（仅创建者）。"""
    assert_user_write(cu)
    f = await _get_visible_ontology_folder(db, folder_id, cu)
    _assert_owner(f, cu)
    f = await rename_ontology_folder(db, f, data.path)
    await db.commit()
    await db.refresh(f)
    return f


@router.delete("/terminal/ontology-folders/{folder_id}", status_code=204)
async def delete_ontology_folder_endpoint(
    folder_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除本体文件夹及其下内容（仅创建者，级联子文件夹与文件）。"""
    assert_user_write(cu)
    f = await _get_visible_ontology_folder(db, folder_id, cu)
    _assert_owner(f, cu)
    await soft_delete_ontology_folder(db, f)
    await db.commit()


@router.get("/terminal/ontology-files", response_model=list[OntologyFileRead])
async def list_ontology_files_endpoint(
    scope_type: str = Query(..., description="organization/department/team/user"),
    scope_id: str | None = Query(default=None),
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """列出选中 scope 下的本体 Markdown 文件（含 content；scope 必须在用户有效集合内）。"""
    if not _scope_in_effective(cu, scope_type, scope_id):
        raise HTTPException(status_code=404, detail="Scope not accessible")
    return await list_ontology_files(db, cu.organization_id, scope_type, scope_id)


@router.post("/terminal/ontology-files", response_model=OntologyFileRead, status_code=201)
async def upsert_ontology_file_endpoint(
    data: OntologyFileCreate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """导入 / 覆盖本体 Markdown 文件（created_by 记为当前用户）；scope 必须在用户有效集合内。"""
    assert_user_write(cu)
    if not _scope_in_effective(cu, data.scope_type, data.scope_id):
        raise HTTPException(status_code=403, detail="无权在该作用域下导入本体")
    f = await upsert_ontology_file(
        db, cu.organization_id, data.scope_type, data.scope_id, data, created_by=cu.id,
    )
    await db.commit()
    await db.refresh(f)
    return f


@router.get("/terminal/ontology-files/{file_id}", response_model=OntologyFileRead)
async def get_ontology_file_endpoint(
    file_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """取本体文件内容（scope 可见即可读）。"""
    return await _get_visible_ontology_file(db, file_id, cu)


@router.patch("/terminal/ontology-files/{file_id}", response_model=OntologyFileRead)
async def update_ontology_file_endpoint(
    file_id: UUID, data: OntologyFileUpdate,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """重命名 / 编辑本体文件内容（仅创建者）。"""
    assert_user_write(cu)
    f = await _get_visible_ontology_file(db, file_id, cu)
    _assert_owner(f, cu)
    f = await update_ontology_file(db, f, data)
    await db.commit()
    await db.refresh(f)
    return f


@router.delete("/terminal/ontology-files/{file_id}", status_code=204)
async def delete_ontology_file_endpoint(
    file_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """删除本体文件（仅创建者）。"""
    assert_user_write(cu)
    f = await _get_visible_ontology_file(db, file_id, cu)
    _assert_owner(f, cu)
    await soft_delete_ontology_file(db, f)
    await db.commit()
