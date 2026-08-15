"""Workspace service — CRUD for workspaces and their files."""

import base64
import hashlib
import mimetypes
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceFile, WorkspaceFolder
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceFileCreate,
    WorkspaceFileUpdate,
    WorkspaceFolderCreate,
    WorkspaceUpdate,
)
from app.services import doc_parser

MAX_WORKSPACE_FILE_BYTES = 5 * 1024 * 1024
MAX_LLM_FILE_CHARS = 100_000


class WorkspaceFileUploadError(ValueError):
    """工作空间原文件上传校验失败。"""


# ── Workspace ──────────────────────────────────────────────────────────

async def create_workspace(db: AsyncSession, org_id: UUID, data: WorkspaceCreate) -> Workspace:
    ws = Workspace(organization_id=org_id, **data.model_dump())
    db.add(ws)
    await db.flush()
    return ws


async def list_workspaces(db: AsyncSession, org_id: UUID) -> list[Workspace]:
    result = await db.execute(
        select(Workspace).where(Workspace.organization_id == org_id, Workspace.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_workspace(db: AsyncSession, ws_id: UUID) -> Workspace | None:
    result = await db.execute(
        select(Workspace).where(Workspace.id == ws_id, Workspace.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_workspace(db: AsyncSession, ws: Workspace, data: WorkspaceUpdate) -> Workspace:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ws, field, value)
    await db.flush()
    await db.refresh(ws)
    return ws


async def soft_delete_workspace(db: AsyncSession, ws: Workspace) -> None:
    ws.deleted_at = datetime.now(UTC)
    await db.flush()


# ── WorkspaceFile ──────────────────────────────────────────────────────

def _normalize_path(path: str) -> str:
    """规范化相对路径，防止越权（剥离前导 / 与 .. 段）。"""
    parts: list[str] = []
    for seg in path.replace("\\", "/").split("/"):
        if seg in ("", ".",):
            continue
        if seg == "..":
            # 不允许上跳
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def _sanitize_content(content: str) -> str:
    """剥离 PostgreSQL TEXT 列不允许的 NUL 字节（\\x00）。

    上传的二进制文件经 readAsText 后可能携带 U+0000，直接落库会触发
    ``CharacterNotInRepertoireError``。工作空间为智能体文本沙箱，二进制内容本就不适用，
    此处做防御性清洗避免 500。
    """
    return content.replace("\x00", "")


async def upsert_file(db: AsyncSession, ws: Workspace, data: WorkspaceFileCreate) -> WorkspaceFile:
    path = _normalize_path(data.path)
    content = _sanitize_content(data.content)
    meta = dict(data.metadata or {})
    # 二进制文件：前端以 base64 编码写入 content，并以 metadata.binary 标记。
    # size / content_hash 按解码后的原始字节计算，content 列存 base64 文本（PG TEXT 不允许 NUL）。
    if meta.get("binary"):
        try:
            raw = base64.b64decode(content, validate=False)
        except ValueError:  # binascii.Error 是 ValueError 子类
            raw = b""
        size = len(raw)
        content_hash = hashlib.sha256(raw).hexdigest()
    else:
        content_bytes = content.encode("utf-8")
        size = len(content_bytes)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
    parse_status = "unparsed" if meta.get("binary") else "ready"
    parse_kind = None if meta.get("binary") else "text"
    # 注意：此处**不**按 ``deleted_at IS NULL`` 过滤。唯一约束 ``uq_wsfile_path`` 是
    # ``(workspace_id, path)`` 且**不含** deleted_at——同一路径即便旧记录已被软删，仍占用
    # 该 (workspace_id, path) 槽位。若按 deleted_at 过滤会漏掉软删记录 → 走 INSERT 分支
    # → 命中唯一约束冲突（UniqueViolation）。这里取同路径记录（无论软删与否）：存在则
    # 复活并覆盖，不存在才 INSERT。
    result = await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws.id,
            WorkspaceFile.path == path,
        )
    )
    f = result.scalar_one_or_none()
    if f is None:
        f = WorkspaceFile(
            workspace_id=ws.id,
            path=path,
            size=size,
            content_hash=content_hash,
            content=content,
            content_ref=path,
            parse_status=parse_status,
            parse_kind=parse_kind,
            metadata_=meta,
        )
        db.add(f)
    else:
        f.content = content
        f.size = size
        f.content_hash = content_hash
        f.extracted_text = None
        f.parse_status = parse_status
        f.parse_kind = parse_kind
        f.parse_error = None
        # 复活被软删的同路径记录：upsert 语义是「该路径现在应是这份内容」，
        # 旧记录的软删状态不应阻挡新写入（否则唯一约束会让 INSERT 失败）。
        f.deleted_at = None
        # 合并而非覆盖：保留既有元数据（如 task_id 归属标记），仅用新值更新同名字段。
        f.metadata_ = {**(f.metadata_ or {}), **meta}
        if not meta.get("binary"):
            f.metadata_.pop("binary", None)
            f.metadata_.pop("mime", None)
    await db.flush()
    await db.refresh(f)
    return f


async def list_files(db: AsyncSession, ws_id: UUID) -> list[WorkspaceFile]:
    result = await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws_id, WorkspaceFile.deleted_at.is_(None)
        ).order_by(WorkspaceFile.path)
    )
    return list(result.scalars().all())


async def get_file(db: AsyncSession, file_id: UUID) -> WorkspaceFile | None:
    result = await db.execute(
        select(WorkspaceFile).where(WorkspaceFile.id == file_id, WorkspaceFile.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_file_by_path(db: AsyncSession, ws_id: UUID, path: str) -> WorkspaceFile | None:
    """按 (workspace_id, path) 取文件（path 经规范化）。供智能体内置文件工具使用。"""
    normalized = _normalize_path(path)
    result = await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws_id,
            WorkspaceFile.path == normalized,
            WorkspaceFile.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def update_file(db: AsyncSession, f: WorkspaceFile, data: WorkspaceFileUpdate) -> WorkspaceFile:
    if data.content is not None:
        content = _sanitize_content(data.content)
        f.content = content
        f.size = len(content.encode("utf-8"))
        f.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        f.extracted_text = None
        f.parse_status = "ready"
        f.parse_kind = "text"
        f.parse_error = None
    if data.metadata is not None:
        f.metadata_ = data.metadata
    await db.flush()
    await db.refresh(f)
    return f


async def soft_delete_file(db: AsyncSession, f: WorkspaceFile) -> None:
    f.deleted_at = datetime.now(UTC)
    await db.flush()


async def ingest_uploaded_file(
    db: AsyncSession,
    ws: Workspace,
    *,
    path: str,
    filename: str,
    content_type: str | None,
    raw: bytes,
) -> WorkspaceFile:
    """保存工作空间原文件并同步提取可预览、可供 LLM 使用的结构化文本。"""
    if not raw:
        raise WorkspaceFileUploadError("文件为空")
    if len(raw) > MAX_WORKSPACE_FILE_BYTES:
        raise WorkspaceFileUploadError(
            f"文件过大（{len(raw)} 字节），上限 {MAX_WORKSPACE_FILE_BYTES // (1024 * 1024)}MB"
        )
    mime = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    encoded = base64.b64encode(raw).decode("ascii")
    f = await upsert_file(db, ws, WorkspaceFileCreate(
        path=path,
        content=encoded,
        metadata={"binary": True, "mime": mime, "name": filename},
    ))
    await _parse_binary_file(db, f, filename=filename, content_type=mime, raw=raw)
    return f


async def reparse_file(db: AsyncSession, f: WorkspaceFile) -> WorkspaceFile:
    """重新解析历史二进制工作空间文件；原始内容不变。"""
    if not (f.metadata_ or {}).get("binary"):
        f.parse_status = "ready"
        f.parse_kind = "text"
        f.parse_error = None
        f.extracted_text = None
        await db.flush()
        await db.refresh(f)
        return f
    try:
        raw = base64.b64decode(f.content or "", validate=False)
    except ValueError as exc:
        f.parse_status = "failed"
        f.parse_error = f"原文件 Base64 损坏：{exc}"
        await db.flush()
        await db.refresh(f)
        return f
    meta = f.metadata_ or {}
    await _parse_binary_file(
        db,
        f,
        filename=str(meta.get("name") or f.path.rsplit("/", 1)[-1]),
        content_type=str(meta.get("mime") or "application/octet-stream"),
        raw=raw,
    )
    return f


async def _parse_binary_file(
    db: AsyncSession,
    f: WorkspaceFile,
    *,
    filename: str,
    content_type: str | None,
    raw: bytes,
) -> None:
    try:
        text, kind = doc_parser.extract_text(filename, content_type, raw)
        if not text.strip():
            raise doc_parser.UnsupportedFileTypeError("文件解析后内容为空")
        f.extracted_text = text
        f.parse_status = "ready"
        f.parse_kind = kind
        f.parse_error = None
    except doc_parser.UnsupportedFileTypeError as exc:
        f.extracted_text = None
        message = str(exc)
        f.parse_status = "unsupported" if message.startswith("不支持的文件类型") else "failed"
        f.parse_kind = None
        f.parse_error = message[:1000]
    await db.flush()
    await db.refresh(f)


def resolve_file_content(f: WorkspaceFile, *, max_chars: int = MAX_LLM_FILE_CHARS) -> str:
    """给智能体读取文件：文本返回原文，二进制返回解析结果，绝不返回 Base64。"""
    if not (f.metadata_ or {}).get("binary"):
        return f.content or ""
    if f.parse_status != "ready" or not (f.extracted_text or "").strip():
        detail = f.parse_error or "尚未解析"
        return f"[文件 {f.path} 无法读取正文：{detail}]"
    text = f.extracted_text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[内容已截断：原文 {len(text)} 字符，本轮最多注入 {max_chars} 字符]"


# ── WorkspaceFolder ────────────────────────────────────────────────────

async def create_folder(db: AsyncSession, ws: Workspace, data: WorkspaceFolderCreate) -> WorkspaceFolder:
    """新建文件夹（幂等）：path 经规范化后按 (workspace_id, path) 去重，已存在则原样返回。"""
    path = _normalize_path(data.path)
    result = await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == ws.id,
            WorkspaceFolder.path == path,
            WorkspaceFolder.deleted_at.is_(None),
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        folder = WorkspaceFolder(workspace_id=ws.id, path=path)
        db.add(folder)
        await db.flush()
        await db.refresh(folder)
    return folder


async def list_folders(db: AsyncSession, ws_id: UUID) -> list[WorkspaceFolder]:
    result = await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == ws_id, WorkspaceFolder.deleted_at.is_(None)
        ).order_by(WorkspaceFolder.path)
    )
    return list(result.scalars().all())


async def get_folder(db: AsyncSession, folder_id: UUID) -> WorkspaceFolder | None:
    result = await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.id == folder_id, WorkspaceFolder.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


async def soft_delete_folder(db: AsyncSession, folder: WorkspaceFolder) -> None:
    """软删文件夹 + 其下所有子文件夹 + 该前缀下所有文件（级联）。

    嵌套靠路径段，故以 ``folder.path + "/"`` 前缀匹配后代与文件。
    """
    now = datetime.now(UTC)
    prefix = f"{folder.path}/"

    # 子文件夹
    sub_folders = (await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == folder.workspace_id,
            WorkspaceFolder.path.startswith(prefix),
            WorkspaceFolder.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_folders:
        sf.deleted_at = now

    # 前缀下文件
    sub_files = (await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == folder.workspace_id,
            WorkspaceFile.path.startswith(prefix),
            WorkspaceFile.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_files:
        sf.deleted_at = now

    folder.deleted_at = now
    await db.flush()


# ── Workspace Tree（随组织架构逐级嵌套）──────────────────────────────────

def _ws_info(ws: Workspace | None) -> dict | None:
    if ws is None:
        return None
    return {
        "id": str(ws.id),
        "name": ws.name,
        "slug": ws.slug,
        "scope_type": ws.scope_type,
        "scope_id": str(ws.scope_id) if ws.scope_id else None,
        "is_active": ws.is_active,
    }


def _node(node_type: str, node_id, name: str, ws: Workspace | None, children: list[dict]) -> dict:
    return {
        "node_type": node_type,
        "node_id": str(node_id),
        "name": name,
        "workspace": _ws_info(ws),
        "children": children,
    }


async def build_workspace_tree(db: AsyncSession, org_ids: list[UUID]) -> list[dict]:
    """构建工作空间文件夹树：组织 → 部门 → 团队 → 用户，每节点携带其绑定工作空间。

    缺失工作空间惰性补建（``ensure_node_workspace``）；用户挂载到所属团队 / 部门 / 组织。
    """
    # 延迟导入以规避与 workspace_lifecycle 的循环依赖。
    from app.services.workspace_lifecycle import ensure_node_workspace

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
        org_ws = await ensure_node_workspace(db, org.id, "organization", None, org.name, org.slug)

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
            # 组织管理员（role='admin'）非终端用户，不持有工作空间：
            # 节点照常展示（前端标「无工作空间」），但不创建/复活其工作空间。
            if u.role == "admin":
                uws = None
            else:
                uws = await ensure_node_workspace(db, org.id, "user", str(u.id), uname, str(u.id))
            unode = _node("user", u.id, uname, uws, [])
            if u.team_id and u.team_id in team_map:
                users_by_team.setdefault(u.team_id, []).append(unode)
            elif u.department_id and u.department_id in dept_map:
                users_by_dept.setdefault(u.department_id, []).append(unode)
            else:
                org_direct_users.append(unode)

        # 按部门组装（团队归其部门）
        depts_sorted = sorted(depts, key=lambda d: d.name)
        dept_nodes: list[dict] = []
        for dept in depts_sorted:
            dept_ws = await ensure_node_workspace(db, org.id, "department", str(dept.id), dept.name, dept.slug)
            dept_teams = [t for t in team_map.values() if t.department_id == dept.id]
            dept_teams = sorted(dept_teams, key=lambda t: t.name)
            team_nodes: list[dict] = []
            for team in dept_teams:
                team_ws = await ensure_node_workspace(db, org.id, "team", str(team.id), team.name, str(team.id))
                team_nodes.append(_node("team", team.id, team.name, team_ws, users_by_team.get(team.id, [])))
            dept_children = team_nodes + users_by_dept.get(dept.id, [])
            dept_nodes.append(_node("department", dept.id, dept.name, dept_ws, dept_children))

        tree.append(_node("organization", org.id, org.name, org_ws, dept_nodes + org_direct_users))

    return tree
