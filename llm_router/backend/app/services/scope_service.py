"""Scope service — resolve a terminal user's effective resource scope.

资源（Skill / 本体 / RagCollection / Workspace）按 ``scope_type`` + ``scope_id`` 分级：
organization（全组织，scope_id 为 None）/ department / team / user。一个资源对用户可见当且仅当
其落在用户的有效 scope 集合内：组织级 + 用户所属部门 + 用户所属团队 + 用户本人。

「自动匹配全部」= 用户有效 scope 集合内的资源并集（终端在 skills/ontology/rag 未指定时由
运行时调用本服务解析为全集）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.user_auth import CurrentUser
from app.models.agent import Agent
from app.models.api_key import ApiKey
from app.models.data_interface import DataInterface, DataSystem
from app.models.ontology import OntologyFile
from app.models.rag import RagCollection
from app.models.skill import SkillFile, SkillFolder
from app.models.workspace import Workspace
from app.services import multimodal_service


def effective_scope_set(cu: CurrentUser) -> list[tuple[str, str | None]]:
    """返回用户有效 scope 集合 [(scope_type, scope_id), ...]。

    organization 级 scope_id 为 None；department/team/user 级为对应 id（未绑定则省略）。
    """
    scopes: list[tuple[str, str | None]] = [("organization", None)]
    if cu.department_id:
        scopes.append(("department", cu.department_id))
    if cu.team_id:
        scopes.append(("team", cu.team_id))
    scopes.append(("user", cu.id))
    return scopes


def scope_filter(model, cu: CurrentUser):
    """构造 ``model`` 的可见性 WHERE 条件（组织级 + 用户 dept/team/user 命中）。"""
    conds = [model.scope_type == "organization"]
    if cu.department_id:
        conds.append((model.scope_type == "department") & (model.scope_id == cu.department_id))
    if cu.team_id:
        conds.append((model.scope_type == "team") & (model.scope_id == cu.team_id))
    conds.append((model.scope_type == "user") & (model.scope_id == cu.id))
    return or_(*conds)


async def list_skills_for_user(db: AsyncSession, cu: CurrentUser) -> list[SkillFolder]:
    """用户可见的技能文件夹（组织级 + 用户 dept/team/user 命中）。

    新版包必须已有活动版本；存量技能只要存在 skill.md 仍兼容显示。
    """
    stmt = select(SkillFolder).where(
        SkillFolder.organization_id == cu.organization_id,
        SkillFolder.deleted_at.is_(None),
        SkillFolder.is_active.is_(True),
        scope_filter(SkillFolder, cu),
        or_(
            SkillFolder.active_version_id.is_not(None),
            exists(select(SkillFile.id).where(
                SkillFile.skill_folder_id == SkillFolder.id,
                SkillFile.path == "skill.md",
                SkillFile.deleted_at.is_(None),
            )),
        ),
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_ontologies_for_user(db: AsyncSession, cu: CurrentUser) -> list[OntologyFile]:
    """用户可见的本体 Markdown 文件（组织级 + 用户 dept/team/user 命中）。

    本体已文件化：返回 OntologyFile（无 is_active 维度，文件即启用）。
    """
    stmt = select(OntologyFile).where(
        OntologyFile.organization_id == cu.organization_id,
        OntologyFile.deleted_at.is_(None),
        scope_filter(OntologyFile, cu),
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_rags_for_user(db: AsyncSession, cu: CurrentUser) -> list[RagCollection]:
    stmt = select(RagCollection).where(
        RagCollection.organization_id == cu.organization_id,
        RagCollection.deleted_at.is_(None),
        scope_filter(RagCollection, cu),
    )
    return list((await db.execute(stmt)).scalars().all())


def is_rag_visible(collection: RagCollection, cu: CurrentUser) -> bool:
    if str(collection.organization_id) != str(cu.organization_id) or collection.deleted_at is not None:
        return False
    if collection.scope_type == "organization":
        return True
    if collection.scope_type == "department":
        return bool(cu.department_id and collection.scope_id == cu.department_id)
    if collection.scope_type == "team":
        return bool(cu.team_id and collection.scope_id == cu.team_id)
    return collection.scope_type == "user" and collection.scope_id == cu.id


async def assert_bound_rags_visible(
    db: AsyncSession, cu: CurrentUser, collection_ids: list[str],
) -> list[RagCollection]:
    """Validate Agent RAG bindings without trusting client-supplied UUIDs."""
    if not collection_ids:
        return []
    try:
        ids = [UUID(str(value)) for value in collection_ids]
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid RAG collection id") from exc
    rows = list((await db.execute(select(RagCollection).where(
        RagCollection.id.in_(ids), RagCollection.deleted_at.is_(None),
    ))).scalars().all())
    by_id = {str(row.id): row for row in rows}
    ordered = []
    for value in collection_ids:
        collection = by_id.get(str(value))
        if collection is None or not is_rag_visible(collection, cu):
            raise HTTPException(status_code=403, detail="RAG collection is not available to this user")
        ordered.append(collection)
    return ordered


async def assert_admin_bound_rags(
    db: AsyncSession, org_id: UUID | str, collection_ids: list[str],
) -> list[RagCollection]:
    if not collection_ids:
        return []
    try:
        ids = [UUID(str(value)) for value in collection_ids]
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid RAG collection id") from exc
    rows = list((await db.execute(select(RagCollection).where(
        RagCollection.id.in_(ids), RagCollection.deleted_at.is_(None),
    ))).scalars().all())
    by_id = {str(row.id): row for row in rows}
    ordered = []
    for value in collection_ids:
        collection = by_id.get(str(value))
        if collection is None or str(collection.organization_id) != str(org_id):
            raise HTTPException(status_code=403, detail="RAG collection belongs to another organization")
        ordered.append(collection)
    return ordered


async def list_data_interfaces_for_user(db: AsyncSession, cu: CurrentUser) -> list[DataInterface]:
    """用户可见的活跃数据接口（按 DataSystem 节点作用域：组织级 + 用户 dept/team/user 命中）。

    数据接口为管理端目录（params/response schema），运行时仅注入上下文 + 留痕，不真正执行。
    预加载 ``system`` 关系以取系统名，避免逐条懒加载产生 N+1。
    """
    stmt = (
        select(DataInterface)
        .join(DataSystem, DataInterface.data_system_id == DataSystem.id)
        .options(selectinload(DataInterface.system))
        .where(
            DataSystem.organization_id == cu.organization_id,
            DataSystem.deleted_at.is_(None),
            DataSystem.is_active.is_(True),
            DataInterface.deleted_at.is_(None),
            DataInterface.is_active.is_(True),
            scope_filter(DataSystem, cu),
        )
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_workspaces_for_user(db: AsyncSession, cu: CurrentUser) -> list[Workspace]:
    stmt = select(Workspace).where(
        Workspace.organization_id == cu.organization_id,
        Workspace.deleted_at.is_(None),
        Workspace.is_active.is_(True),
        scope_filter(Workspace, cu),
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_agents_for_user(db: AsyncSession, cu: CurrentUser) -> list[Agent]:
    """用户可见的活跃智能体（组织级 + 用户 dept/team/user 命中）。

    供终端「选智能体」下拉：返回 Agent 行（已加 scope_type/scope_id 列），
    仅 is_active 且未删除者。终端选中后以 template_agent_id 逐次覆盖运行（不落库）。
    """
    stmt = select(Agent).where(
        Agent.organization_id == cu.organization_id,
        Agent.deleted_at.is_(None),
        Agent.is_active.is_(True),
        scope_filter(Agent, cu),
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_user_workspace(db: AsyncSession, cu: CurrentUser) -> Workspace | None:
    """用户的个人工作空间（scope_type=user，scope_id=用户 id）。终端默认工作空间取此。"""
    stmt = select(Workspace).where(
        Workspace.organization_id == cu.organization_id,
        Workspace.scope_type == "user",
        Workspace.scope_id == cu.id,
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def is_workspace_visible(ws: Workspace, cu: CurrentUser) -> bool:
    """运行时校验某个 workspace 是否落在用户 scope 内（终端文件读写守卫）。"""
    if ws.scope_type == "organization":
        return True
    if ws.scope_type == "department" and cu.department_id and ws.scope_id == cu.department_id:
        return True
    if ws.scope_type == "team" and cu.team_id and ws.scope_id == cu.team_id:
        return True
    if ws.scope_type == "user" and ws.scope_id == cu.id:
        return True
    return False


async def list_api_keys_for_user(db: AsyncSession, cu: CurrentUser) -> list[ApiKey]:
    """用户可访问的活跃 API Key（组织级 + 所属部门 + 所属团队；未过期、未吊销）。

    ApiKey 仅按 organization/department/team 三级分发（无 user 级），故用户可见集 =
    组织级 Key ∪ 其部门级 Key ∪ 其团队级 Key。
    """
    now = datetime.now(UTC)
    conds: list = [ApiKey.scope_type == "organization"]
    if cu.department_id:
        conds.append((ApiKey.scope_type == "department") & (ApiKey.department_id == cu.department_id))
    if cu.team_id:
        conds.append((ApiKey.scope_type == "team") & (ApiKey.team_id == cu.team_id))
    stmt = select(ApiKey).where(
        ApiKey.organization_id == cu.organization_id,
        ApiKey.is_active.is_(True),
        ApiKey.revoked_at.is_(None),
        or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
        or_(*conds),
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_available_models_for_user(
    db: AsyncSession, cu: CurrentUser,
) -> list[str]:
    """用户可用的模型名（按可访问 API Key 聚合，embedding 模型已过滤）。

    模型名按可访问 API Key 聚合：任一 Key 的 ``allowed_models`` 为空（= 不限模型）→ 组织全部
    活跃 provider 的 ``supported_models`` 并集；否则 → 各 Key 的 ``allowed_models`` 并集。
    返回的模型名可直接填入 ``TaskConfig.model_alias``（真实模型 id，或 "default" 走组织默认路由）。

    embedding 类模型（名字含 ``embed``，不区分大小写）一律过滤——任务配置只关心对话/生成类模型。
    """
    keys = await list_api_keys_for_user(db, cu)

    providers = await multimodal_service.visible_providers(
        db, cu.organization_id, dept_id=cu.department_id, team_id=cu.team_id,
    )
    provider_models: list[str] = []
    for p in providers:
        provider_models.extend(p.supported_models or [])

    if any(not k.allowed_models for k in keys):
        # 存在不限模型的 Key → 用户可调用 provider 全集
        models = sorted(set(provider_models))
    else:
        models = sorted({m for k in keys for m in (k.allowed_models or [])})

    # 过滤 embedding 模型：任务配置只列对话/生成类，避免误选无法 chat 的嵌入模型
    generation_models = {
        model for provider in providers
        if (model := multimodal_service.provider_image_generation_model(provider))
    }
    return [m for m in models if "embed" not in m.lower() and m not in generation_models]


async def terminal_model_capabilities(db: AsyncSession, cu: CurrentUser, models: list[str]) -> dict:
    """Return additive multimodal metadata without changing the legacy models array."""
    capabilities = await multimodal_service.model_capabilities_for_scope(
        db, cu.organization_id, models, dept_id=cu.department_id, team_id=cu.team_id,
    )
    fallback = await multimodal_service.resolve_vision_fallback(
        db, cu.organization_id, dept_id=cu.department_id, team_id=cu.team_id,
    )
    image_generation = await multimodal_service.resolve_image_generation(
        db, cu.organization_id, dept_id=cu.department_id, team_id=cu.team_id,
    )
    return {
        "capabilities": capabilities,
        "vision_fallback_available": fallback is not None,
        "image_generation_available": image_generation is not None,
    }
