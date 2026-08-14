"""Memory service — CRUD for hierarchical long-term memory + runtime load.

组织/部门/团队级记忆由管理端维护（manual）；个人级（scope_type='user'）每个非管理员用户
**只有一份**：系统端建/改用户时同步的「个人档案」与终端智能体经 ``extract_memory`` 沉淀的
「沉淀记忆」均合并进同一条记录（markdown 分节：``## 个人档案`` 可覆写、``## 沉淀记忆`` 逐条
追加去重）。运行时 ``load_memory`` 按用户的 4 级 scope 聚合 recent top-N 注入 system_prompt。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory
from app.models.organization import Organization
from app.models.department import Department
from app.models.team import Team
from app.models.user import User
from app.schemas.memory import MemoryCreate, MemoryUpdate

# 个人记忆 markdown 分节标题
PROFILE_SECTION = "个人档案"
FACTS_SECTION = "沉淀记忆"


# ── markdown 分节合并工具 ──────────────────────────────────────────────

def _build_profile_section(
    name: str | None, org_name: str | None, dept_name: str | None, team_name: str | None,
) -> str:
    """构建「## 个人档案」分节（无任何归属信息时返回空串）。"""
    lines: list[str] = []
    if name:
        lines.append(f"- 姓名：{name}")
    if org_name:
        lines.append(f"- 所属组织：{org_name}")
    if dept_name:
        lines.append(f"- 所属部门：{dept_name}")
    if team_name:
        lines.append(f"- 所属团队：{team_name}")
    if not lines:
        return ""
    return f"## {PROFILE_SECTION}\n" + "\n".join(lines)


def _section_bounds(lines: list[str], header: str) -> tuple[int, int] | None:
    """返回 `## {header}` 分节的 [start, end) 行号；end 为下一个 `## ` 行或末尾。"""
    header_line = f"## {header}"
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == header_line:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def _replace_section(content: str, header: str, new_section: str) -> str:
    """用 new_section 替换 `## {header}` 分节；分节不存在则前置。保留其余分节。"""
    lines = (content or "").split("\n")
    bounds = _section_bounds(lines, header)
    if bounds is None:
        # 不存在该分节：前置（与已有内容空一行分隔）
        body = new_section.split("\n")
        merged = body + ([""] + lines if lines and any(l.strip() for l in lines) else lines)
        return "\n".join(merged).strip("\n")
    start, end = bounds
    merged = lines[:start] + new_section.split("\n") + lines[end:]
    return "\n".join(merged).strip("\n")


def _append_fact(content: str, fact: str) -> str:
    """把 fact 作为列表项追加到 `## 沉淀记忆` 分节；分节不存在则新建；完全重复则跳过。"""
    fact = (fact or "").strip().lstrip("-").strip()
    if not fact:
        return content or ""
    bullet = f"- {fact}"
    lines = (content or "").split("\n")
    bounds = _section_bounds(lines, FACTS_SECTION)
    if bounds is None:
        # 无沉淀记忆分节：追加到末尾
        section = [f"## {FACTS_SECTION}", bullet]
        if content and content.strip():
            return "\n".join(lines).rstrip("\n") + "\n\n" + "\n".join(section)
        return "\n".join(section)
    start, end = bounds
    section_lines = lines[start:end]
    if any(ln.strip() == bullet for ln in section_lines):
        return content  # 去重
    merged = lines[:end] + [bullet] + lines[end:]
    return "\n".join(merged)


# ── CRUD ───────────────────────────────────────────────────────────────


async def create_memory(db: AsyncSession, org_id: UUID, data: MemoryCreate, created_by: str | None = None) -> Memory:
    mem = Memory(organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(mem)
    await db.flush()
    return mem


async def list_memory(
    db: AsyncSession, org_id: UUID,
    scope_type: str | None = None, scope_id: str | None = None,
) -> list[Memory]:
    stmt = select(Memory).where(Memory.organization_id == org_id, Memory.deleted_at.is_(None))
    if scope_type:
        stmt = stmt.where(Memory.scope_type == scope_type)
    if scope_id:
        stmt = stmt.where(Memory.scope_id == scope_id)
    stmt = stmt.order_by(Memory.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


async def list_memory_for_user(
    db: AsyncSession, org_id: UUID,
    scopes: list[tuple[str, str | None]],
) -> list[Memory]:
    """终端用户可见记忆：4 级 scope 并集（org + dept + team + user）。"""
    conds = []
    for st, sid in scopes:
        if st == "organization":
            conds.append((Memory.scope_type == "organization"))
        else:
            if sid:
                conds.append((Memory.scope_type == st) & (Memory.scope_id == sid))
    if not conds:
        return []
    stmt = (
        select(Memory)
        .where(Memory.organization_id == org_id, Memory.deleted_at.is_(None), or_(*conds))
        .order_by(Memory.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def load_memory_for_scopes(
    db: AsyncSession, org_id: UUID,
    scopes: list[tuple[str, str | None]],
    per_scope_limit: int = 8,
) -> list[dict]:
    """运行时载入：按 scope 分级取最近 N 条，返回 [{scope_type, scope_id, category, content}]。

    v1 按 recency 取每级 top-N（向量语义召回留作扩展）。组织级 scope_id 为 None。
    """
    rows = await list_memory_for_user(db, org_id, scopes)
    # 按 scope 分组取最近 N 条
    bucket: dict[tuple[str, str | None], list[Memory]] = {}
    for m in rows:
        key = (m.scope_type, m.scope_id)
        bucket.setdefault(key, []).append(m)
    out: list[dict] = []
    for key, items in bucket.items():
        # rows 已按 created_at desc，取前 N
        for m in items[:per_scope_limit]:
            out.append({
                "scope_type": m.scope_type,
                "scope_id": str(m.scope_id) if m.scope_id else None,
                "category": m.category,
                "content": m.content,
                "source": m.source,
            })
    return out


async def _get_personal_memory(
    db: AsyncSession, org_id: UUID, user_id: str,
) -> Memory | None:
    """取某用户唯一一条个人记忆（scope_type='user'）。用 ``.first()`` 容忍存量重复。"""
    return (await db.execute(
        select(Memory).where(
            Memory.organization_id == org_id,
            Memory.scope_type == "user",
            Memory.scope_id == user_id,
            Memory.deleted_at.is_(None),
        ).order_by(Memory.created_at.asc())
    )).scalars().first()


async def add_user_memory(
    db: AsyncSession, org_id: UUID, user_id: str, content: str,
) -> Memory:
    """智能体沉淀个人级记忆（extract_memory 节点调用）。

    合并进该用户唯一一条个人记忆的 ``## 沉淀记忆`` 分节（逐条追加、去重）；
    记录不存在则新建。不再为每条事实单独建行。
    """
    mem = await _get_personal_memory(db, org_id, user_id)
    if mem is None:
        mem = Memory(
            organization_id=org_id,
            scope_type="user",
            scope_id=user_id,
            category="personal",
            content=_append_fact("", content),
            source="auto",
            metadata_={},
        )
        db.add(mem)
        await db.flush()
        return mem
    mem.content = _append_fact(mem.content or "", content)
    await db.flush()
    return mem


async def upsert_user_profile_memory(
    db: AsyncSession,
    org_id: UUID,
    user_id: str,
    name: str | None,
    org_name: str | None,
    dept_name: str | None,
    team_name: str | None,
) -> Memory:
    """新建/编辑用户时同步个人档案记忆。

    合并进该用户唯一一条个人记忆的 ``## 个人档案`` 分节（覆写姓名/组织/部门/团队，
    保留 ``## 沉淀记忆`` 等其它分节）；记录不存在则新建。category 统一为 'personal'。
    """
    profile_section = _build_profile_section(name, org_name, dept_name, team_name)
    metadata = {
        "name": name,
        "organization": org_name,
        "department": dept_name,
        "team": team_name,
    }

    mem = await _get_personal_memory(db, org_id, user_id)
    if mem is None:
        content = profile_section or f"## {PROFILE_SECTION}\n（暂无归属信息）"
        mem = Memory(
            organization_id=org_id,
            scope_type="user",
            scope_id=user_id,
            category="personal",
            content=content,
            source="manual",
            metadata_=metadata,
        )
        db.add(mem)
        await db.flush()
        return mem

    if profile_section:
        mem.content = _replace_section(mem.content or "", PROFILE_SECTION, profile_section)
    mem.metadata_ = metadata
    await db.flush()
    return mem


async def consolidate_user_memory(
    db: AsyncSession,
    org_id: UUID,
    user_id: str,
    name: str | None,
    org_name: str | None,
    dept_name: str | None,
    team_name: str | None,
) -> dict:
    """一次性合并某用户存量多条个人记忆为一条 markdown 分节记录，软删多余行。

    用于历史数据迁移：旧版每条事实单独成行、profile 单独成行，此处汇聚到一条
    （``## 个人档案`` 来自入参，``## 沉淀记忆`` 来自旧 auto 行的内容）。运行时
    ``add_user_memory`` / ``upsert_user_profile_memory`` 已不再产生多行。
    """
    rows = list((await db.execute(
        select(Memory).where(
            Memory.organization_id == org_id,
            Memory.scope_type == "user",
            Memory.scope_id == user_id,
            Memory.deleted_at.is_(None),
        ).order_by(Memory.created_at.asc())
    )).scalars().all())

    # 收集旧 auto/其它行的内容作为沉淀事实（每行一条，去重保序）
    facts: list[str] = []
    for m in rows:
        if m.category == "profile":
            continue
        for ln in (m.content or "").splitlines():
            ln = ln.strip().lstrip("-").strip()
            if ln and ln not in facts:
                facts.append(ln)

    parts: list[str] = []
    profile_section = _build_profile_section(name, org_name, dept_name, team_name)
    if profile_section:
        parts.append(profile_section)
    elif rows:
        parts.append(f"## {PROFILE_SECTION}\n（暂无归属信息）")
    if facts:
        parts.append(f"## {FACTS_SECTION}\n" + "\n".join(f"- {f}" for f in facts))
    new_content = "\n\n".join(parts)
    metadata = {
        "name": name, "organization": org_name, "department": dept_name, "team": team_name,
    }

    survivor = next((m for m in rows if m.category == "profile"), None) or (rows[0] if rows else None)
    if survivor is None:
        survivor = Memory(
            organization_id=org_id, scope_type="user", scope_id=user_id,
            category="personal", content=new_content, source="manual", metadata_=metadata,
        )
        db.add(survivor)
    else:
        survivor.content = new_content
        survivor.category = "personal"
        survivor.metadata_ = metadata

    now = datetime.now(UTC)
    removed = 0
    for m in rows:
        if m is survivor:
            continue
        m.deleted_at = now
        removed += 1
    await db.flush()
    return {"survivor": survivor, "removed": removed}


async def get_memory(db: AsyncSession, mem_id: UUID) -> Memory | None:
    return (await db.execute(
        select(Memory).where(Memory.id == mem_id, Memory.deleted_at.is_(None))
    )).scalar_one_or_none()


async def update_memory(db: AsyncSession, mem: Memory, data: MemoryUpdate) -> Memory:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(mem, field, value)
    await db.flush()
    await db.refresh(mem)
    return mem


async def soft_delete_memory(db: AsyncSession, mem: Memory) -> None:
    mem.deleted_at = datetime.now(UTC)
    await db.flush()


# ── 记忆树（随组织架构逐级嵌套）─────────────────────────────────────────

def _mem_info(m: Memory | None) -> dict | None:
    if m is None:
        return None
    # 不返回 created_at/updated_at：二者为 server_default，新建对象 flush 后未加载，
    # 异步访问会触发懒加载报错（与工作空间树 _ws_info 一致，只读非时间戳列）。
    return {
        "id": str(m.id),
        "scope_type": m.scope_type,
        "scope_id": str(m.scope_id) if m.scope_id else None,
        "category": m.category,
        "content": m.content,
        "source": m.source,
    }


def _mnode(node_type: str, node_id, name: str, mem: Memory | None, children: list[dict]) -> dict:
    return {
        "node_type": node_type,
        "node_id": str(node_id),
        "name": name,
        "memory": _mem_info(mem),
        "children": children,
    }


async def build_memory_tree(db: AsyncSession, org_ids: list[UUID]) -> list[dict]:
    """构建长期记忆树：组织 → 部门 → 团队 → 用户，每节点携带其绑定记忆。

    缺失记忆惰性补建/刷新（org/dept/team 走 ``ensure_node_memory``，user 走
    ``upsert_user_profile_memory``）；组织管理员（role='admin'）非终端用户，不持有个人记忆，
    节点照常展示但 memory=None。用户挂载到所属团队 / 部门 / 组织。
    """
    # 延迟导入以规避与 memory_lifecycle 的循环依赖。
    from app.services.memory_lifecycle import ensure_node_memory

    if not org_ids:
        return []

    rows = (await db.execute(
        select(Organization).where(
            Organization.id.in_(org_ids), Organization.deleted_at.is_(None)
        )
    )).scalars().all()
    orgs = sorted(rows, key=lambda o: o.name)

    tree: list[dict] = []
    for org in orgs:
        org_mem = await ensure_node_memory(db, org.id, "organization", None, org_name=org.name)

        depts = list((await db.execute(
            select(Department).where(
                Department.organization_id == org.id, Department.deleted_at.is_(None)
            )
        )).scalars().all())
        dept_map: dict[UUID, Department] = {d.id: d for d in depts}

        all_teams = list((await db.execute(
            select(Team).where(
                Team.organization_id == org.id, Team.deleted_at.is_(None)
            )
        )).scalars().all())
        team_map: dict[UUID, Team] = {t.id: t for t in all_teams}

        users = list((await db.execute(
            select(User).where(
                User.organization_id == org.id, User.deleted_at.is_(None)
            )
        )).scalars().all())

        # 先按 team / dept / org 分桶用户节点
        users_by_team: dict[UUID, list[dict]] = {}
        users_by_dept: dict[UUID, list[dict]] = {}
        org_direct_users: list[dict] = []
        for u in users:
            uname = u.display_name or u.username
            if u.role == "admin":
                # 组织管理员非终端用户，不持有个人记忆：节点展示但 memory=None。
                umem = None
            else:
                dept_name = dept_map[u.department_id].name if u.department_id and u.department_id in dept_map else None
                team_name = team_map[u.team_id].name if u.team_id and u.team_id in team_map else None
                umem = await upsert_user_profile_memory(
                    db, org.id, str(u.id), uname, org.name, dept_name, team_name,
                )
            unode = _mnode("user", u.id, uname, umem, [])
            if u.team_id and u.team_id in team_map:
                users_by_team.setdefault(u.team_id, []).append(unode)
            elif u.department_id and u.department_id in dept_map:
                users_by_dept.setdefault(u.department_id, []).append(unode)
            else:
                org_direct_users.append(unode)

        depts_sorted = sorted(depts, key=lambda d: d.name)
        dept_nodes: list[dict] = []
        for dept in depts_sorted:
            dept_mem = await ensure_node_memory(
                db, org.id, "department", str(dept.id),
                org_name=org.name, dept_name=dept.name,
            )
            dept_teams = [t for t in team_map.values() if t.department_id == dept.id]
            dept_teams = sorted(dept_teams, key=lambda t: t.name)
            team_nodes: list[dict] = []
            for team in dept_teams:
                team_mem = await ensure_node_memory(
                    db, org.id, "team", str(team.id),
                    org_name=org.name, dept_name=dept.name, team_name=team.name,
                )
                team_nodes.append(_mnode("team", team.id, team.name, team_mem, users_by_team.get(team.id, [])))
            dept_children = team_nodes + users_by_dept.get(dept.id, [])
            dept_nodes.append(_mnode("department", dept.id, dept.name, dept_mem, dept_children))

        tree.append(_mnode("organization", org.id, org.name, org_mem, dept_nodes + org_direct_users))

    return tree
