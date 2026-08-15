"""RAG service — collection/document/folder CRUD + chunking + embedding + retrieval."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm_client
from app.database import async_session_factory
from app.models.organization import Organization
from app.models.rag import RagChunk, RagCollection, RagDocument, RagFolder
from app.schemas.rag import (
    RagCollectionCreate,
    RagCollectionUpdate,
    RagDocumentCreate,
    RagDocumentStatusRead,
    RagDocumentUpdate,
    RagFolderCreate,
    RagFolderUpdate,
    RagIngestConfig,
    RagReingestRequest,
    RagRetrieveRequest,
)
from app.services import doc_parser

logger = structlog.get_logger()

# 后台嵌入分批大小：每批调一次 embedding 接口，批后更新 progress 供前端轮询
_EMBED_BATCH = 8


class EmbeddingError(RuntimeError):
    """embedding 调用失败（供应商未配置 / 接口不可用 / 返回向量数不符）。

    入库链路（``ingest_document`` / ``reingest_document``）将其抛出由 API 层转 502，
    不再静默写 ``embedding=NULL`` 假装成功。检索路径 ``retrieve`` 不抛此异常——
    query embed 失败仍降级到关键词检索（在线容错）。
    """

# ── Collection ─────────────────────────────────────────────────────────

async def create_collection(
    db: AsyncSession, org_id: UUID, data: RagCollectionCreate, created_by: str | None = None,
) -> RagCollection:
    """新建集合。slug 未提供或为空时自动生成（中文等非 ASCII 名称无法 slugify，
    且新设计中集合归属由 scope_type/scope_id 决定、不再依赖 slug 绑定节点，
    故服务端生成唯一 slug 以避免 (org, slug) 冲突）。``created_by`` 记录创建者
    （终端用户 id），供「仅可操作自己创建的」授权使用；admin 不传则留空。"""
    dump = data.model_dump()
    if not dump.get("slug"):
        dump["slug"] = f"kb-{uuid4().hex[:12]}"
    coll = RagCollection(organization_id=org_id, created_by=created_by, **dump)
    db.add(coll)
    await db.flush()
    return coll


async def list_collections(
    db: AsyncSession, org_id: UUID,
    scope_type: str | None = None, scope_id: str | None = None,
) -> list[RagCollection]:
    """列出组织下集合；指定 scope 时按 scope_type + scope_id 过滤。

    organization 级 scope_id 为 None；其余级 scope_id 精确匹配。
    """
    stmt = select(RagCollection).where(
        RagCollection.organization_id == org_id, RagCollection.deleted_at.is_(None)
    )
    if scope_type:
        if scope_type == "organization":
            # 组织级：scope_id 应为空
            stmt = stmt.where(RagCollection.scope_type == "organization", RagCollection.scope_id.is_(None))
        else:
            stmt = stmt.where(
                RagCollection.scope_type == scope_type,
                RagCollection.scope_id == scope_id,
            )
    return list((await db.execute(stmt)).scalars().all())


async def get_collection(db: AsyncSession, coll_id: UUID) -> RagCollection | None:
    result = await db.execute(
        select(RagCollection).where(RagCollection.id == coll_id, RagCollection.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_collection(db: AsyncSession, coll: RagCollection, data: RagCollectionUpdate) -> RagCollection:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(coll, field, value)
    await db.flush()
    await db.refresh(coll)
    return coll


async def soft_delete_collection(db: AsyncSession, coll: RagCollection) -> None:
    coll.deleted_at = datetime.now(UTC)
    await db.flush()


# ── Document ingest (chunk + embed) ────────────────────────────────────

# ATX 标题：``# 标题`` ~ ``###### 标题``（CommonMark 要求 # 后空白或行尾）
_ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})(?:[ \t]+|[ \t]*$)(.*?)(?:[ \t]+#+)?[ \t]*$")
# 围栏代码块：``` ``` 或 ~~~（≥3 个）
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*(\S*)")


def _looks_like_markdown(text: str) -> bool:
    """启发式判断是否为 markdown：前 200 行出现 ATX 标题或围栏代码块即认定。

    .md 文件若无任何标题/围栏（纯段落），则按普通文本段落打包，效果同样优于字符滑窗。
    """
    for line in text.splitlines()[:200]:
        if _ATX_HEADING_RE.match(line) or _FENCE_RE.match(line):
            return True
    return False


def _slide(text: str, chunk_size: int, overlap: int) -> list[str]:
    """单段超长时的字符滑窗兜底（仅在结构打包无法装下时使用）。"""
    if len(text) <= chunk_size:
        return [text]
    step = max(1, chunk_size - overlap)
    out: list[str] = []
    i = 0
    while i < len(text):
        out.append(text[i:i + chunk_size])
        if i + chunk_size >= len(text):
            break
        i += step
    return out


def _prefixed(crumb: str, body: str) -> str:
    """把章节面包屑（heading 路径）作为前缀写回块首，保留检索上下文。

    若块本身已是标题开头（含原标题行），不再重复加前缀。``crumb`` 形如
    ``一、合同审查要点 > 1.1 主体资格审查``，写入为合成标题 ``# <crumb>``。
    """
    if not crumb or not body:
        return body
    if body.lstrip().startswith("#"):
        return body
    return f"# {crumb}\n\n{body}"


def _split_paragraphs(text: str, chunk_size: int, overlap: int) -> list[str]:
    """按段落（空行分隔）贪婪打包；单个段落超长才字符滑窗。围栏代码块不拆。

    用于纯文本，以及 markdown 单个 section 内部超 chunk_size 时的二次切分。
    """
    paras: list[str] = []
    cur: list[str] = []
    in_fence = False
    fence_char = ""
    n_f = 0
    for line in text.splitlines():
        if in_fence:
            cur.append(line)
            s = line.strip()
            if s and len(s) >= n_f and set(s) == {fence_char}:
                in_fence = False
            continue
        m = _FENCE_RE.match(line)
        if m:
            if any(x.strip() for x in cur):
                paras.append("\n".join(cur).strip())
                cur = []
            fence_char = m.group(1)[0]
            n_f = len(m.group(1))
            in_fence = True
            cur = [line]
            continue
        if not line.strip():
            if any(x.strip() for x in cur):
                paras.append("\n".join(cur).strip())
                cur = []
            continue
        cur.append(line)
    if any(x.strip() for x in cur):
        paras.append("\n".join(cur).strip())

    chunks: list[str] = []
    acc = ""
    for p in paras:
        if len(p) > chunk_size:
            if acc:
                chunks.append(acc)
                acc = ""
            chunks.extend(_slide(p, chunk_size, overlap))
            continue
        cand = p if not acc else f"{acc}\n\n{p}"
        if len(cand) <= chunk_size:
            acc = cand
        else:
            chunks.append(acc)
            acc = p
    if acc:
        chunks.append(acc)
    return chunks or ([text] if text else [])


def _md_sections(text: str) -> list[tuple[str, str]]:
    """按标题切 section：每个 ATX 标题开启新 section，其后至下一标题前的内容归入该 section。

    返回 ``[(crumb, body), ...]``：``crumb`` 为当前标题层级路径（``> `` 连接），
    ``body`` 为标题行 + 其下属段落/列表/表格/围栏。首标题前的前言自成一段（crumb 为空）。
    """
    lines = text.splitlines()
    n = len(lines)
    i = 0
    headings: list[tuple[int, str]] = []
    sections: list[tuple[str, str]] = []
    cur: list[str] = []

    def crumb() -> str:
        return " > ".join(h for _, h in headings) if headings else ""

    def flush() -> None:
        body = "\n".join(cur).strip()
        if body:
            sections.append((crumb(), body))

    while i < n:
        line = lines[i]
        if not line.strip():
            if cur:
                cur.append("")
            i += 1
            continue

        m = _ATX_HEADING_RE.match(line)
        if m:
            flush()
            cur = []
            level = len(m.group(1))
            htext = m.group(2).strip().strip("#").strip()
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, htext))
            cur = [line.strip()]
            i += 1
            continue

        m = _FENCE_RE.match(line)
        if m:
            fence_char = m.group(1)[0]
            n_f = len(m.group(1))
            buf = [line]
            i += 1
            while i < n:
                nxt = lines[i]
                buf.append(nxt)
                s = nxt.strip()
                if s and len(s) >= n_f and set(s) == {fence_char}:
                    i += 1
                    break
                i += 1
            if cur and cur[-1] != "":
                cur.append("")
            cur.extend(buf)
            continue

        # 段落 / 列表 / 表格：收集到空行、标题或围栏为止（整体不拆）
        buf = [line]
        i += 1
        while i < n:
            nxt = lines[i]
            if not nxt.strip():
                break
            if _ATX_HEADING_RE.match(nxt) or _FENCE_RE.match(nxt):
                break
            buf.append(nxt)
            i += 1
        if cur and cur[-1] != "":
            cur.append("")
        cur.extend(buf)

    flush()
    return sections


def _split_markdown(text: str, chunk_size: int, overlap: int) -> list[str]:
    """markdown 结构感知分块：按 section（标题 + 正文）打包，超长 section 内部按段落再切。

    - section ≤ chunk_size：整段一块，标题随正文一起走，绝不拦腰截断。
    - section > chunk_size：内部按段落贪婪打包，仍超长的单段才字符滑窗；每块带章节面包屑前缀。
    """
    sections = _md_sections(text)
    if not sections:
        return _split_paragraphs(text, chunk_size, overlap)
    chunks: list[str] = []
    for crumb, body in sections:
        if len(body) <= chunk_size:
            chunks.append(_prefixed(crumb, body))
            continue
        # section 超长：剥出首行标题，使其与切分后的首段绑定，避免标题成孤块
        body_lines = body.split("\n")
        head = ""
        rest = body
        if body_lines and body_lines[0].lstrip().startswith("#"):
            head = body_lines[0] + "\n\n"
            rest = "\n".join(body_lines[1:]).lstrip("\n")
        pieces = _split_paragraphs(rest, chunk_size, overlap) or [rest]
        first = head + pieces[0]
        if len(first) <= chunk_size:
            pieces[0] = first
        # 标题 + 首段仍超限时不再单独发标题孤块：标题文本已在每块面包屑前缀中保留
        for piece in pieces:
            chunks.append(_prefixed(crumb, piece))
    return chunks


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """结构感知分块：markdown 走 section 打包，纯文本走段落打包，超长段才字符滑窗。

    旧实现按字符长度滑窗硬切，无视标题/段落/列表边界，导致 md 文档被拆得支离破碎。
    现按文档结构（标题、空行、围栏）切分，标题随其正文一起走，代码块永不拦腰切。
    """
    if chunk_size <= 0:
        return [text]
    if not text or not text.strip():
        return [text]
    if _looks_like_markdown(text):
        return _split_markdown(text, chunk_size, overlap) or [text]
    return _split_paragraphs(text, chunk_size, overlap) or [text]


async def ingest_document(
    db: AsyncSession, coll: RagCollection, org_id: UUID, data: RagDocumentCreate, created_by: str | None = None,
) -> RagDocument:
    """同步入库（终端 JSON 文本 / 既有文本粘贴路径）：写入源文档，分块并嵌入向量。

    embedding 失败时清理半成品分块并抛出 ``EmbeddingError``，由 API 层将文档状态
    持久化为 ``failed`` 并返回 502。``created_by`` 记录创建者（终端用户 id）。
    与上传文件入库不同，此处在请求线程内一次性完成分块+嵌入。
    """
    doc = RagDocument(
        collection_id=coll.id,
        source=data.source,
        title=data.title,
        content=data.content,
        metadata_=data.metadata,
        folder_path=_normalize_path(data.folder_path),
        created_by=created_by,
        status="ready",
        progress=100,
    )
    db.add(doc)
    await db.flush()

    chunks = _split_text(data.content, coll.chunk_size, coll.chunk_overlap)
    await _chunk_and_embed(db, doc, coll, org_id, chunks)
    return doc


async def _chunk_and_embed(
    db: AsyncSession,
    doc: RagDocument,
    coll: RagCollection,
    org_id: UUID,
    chunks: list[str],
    *,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> None:
    """删除旧分块 → 分批嵌入 → 写入 RagChunk → 置 ready/100。

    embedding 失败时清理已写入的半成品分块、将文档置为 ``failed`` 并抛出异常。
    ``on_progress`` 为异步回调 ``(done, total)``，在每批嵌入完成后调用，供后台任务
    更新 progress 并 commit（使其对轮询可见）。同步入库路径不传 ``on_progress``。
    """
    # 删除旧分块（RagChunk 无软删列，物理删除；新建入库时无旧分块，delete 为空操作）
    await db.execute(delete(RagChunk).where(RagChunk.document_id == doc.id))

    total = len(chunks)
    for start in range(0, total, _EMBED_BATCH):
        batch = chunks[start:start + _EMBED_BATCH]
        try:
            vectors = await llm_client.embed(db, org_id, coll.embedding_model, batch)
        except Exception as exc:  # noqa: BLE001 — 嵌入是入库契约的一部分，失败即 fail loud
            # 清理本批之前已 flush 的半成品 chunk，置 failed 供调用方 commit 落库排查
            await db.execute(delete(RagChunk).where(RagChunk.document_id == doc.id))
            doc.status = "failed"
            doc.parse_error = f"embedding 失败：{exc}"[:1000]
            await db.flush()
            raise EmbeddingError(str(exc)) from exc
        if not vectors or len(vectors) != len(batch):
            await db.execute(delete(RagChunk).where(RagChunk.document_id == doc.id))
            doc.status = "failed"
            got = len(vectors) if vectors else 0
            doc.parse_error = f"embedding 返回向量数 {got} 与批大小 {len(batch)} 不符"[:1000]
            await db.flush()
            raise EmbeddingError(f"embedding 返回向量数 {got} 与批大小 {len(batch)} 不符")
        for i, (text, vec) in enumerate(zip(batch, vectors, strict=False)):
            db.add(RagChunk(
                collection_id=coll.id,
                document_id=doc.id,
                content=text,
                embedding=vec,
                metadata_={"chunk_index": start + i},
            ))
        await db.flush()
        if on_progress is not None:
            await on_progress(min(start + len(batch), total), total)

    doc.status = "ready"
    doc.progress = 100
    doc.parse_error = None
    await db.flush()


async def ingest_uploaded_file(
    db: AsyncSession,
    coll: RagCollection,
    org_id: UUID,
    *,
    filename: str,
    content_type: str | None,
    raw: bytes,
    title: str | None = None,
    folder_path: str = "",
    created_by: str | None = None,
) -> RagDocument:
    """上传文件入库：请求线程内同步解析抽取文本并落库，分块+嵌入交后台任务异步进行。

    解析失败抛 :class:`doc_parser.UnsupportedFileTypeError`（API 层转 422）。成功后立即
    ``commit``（而非仅 flush），保证轮询端点在后台任务完成前即可读到 ``pending`` 行；
    随后 ``create_task`` 启动后台嵌入，``ingest_uploaded_file`` 自身不再持有后台 session。
    """
    text, kind = doc_parser.extract_text(filename, content_type, raw)
    if not text.strip():
        raise doc_parser.UnsupportedFileTypeError("文件解析后内容为空")

    normalized_path = _normalize_path(folder_path)
    # 文件夹上传时 folder_path 可能含子目录；补建每一级 RagFolder（幂等），
    # 否则这些目录不会出现在 Finder、文档也会因 folder_path 非根而「隐形」。
    await _ensure_folder_chain(db, coll, normalized_path, created_by=created_by)

    doc = RagDocument(
        collection_id=coll.id,
        source=filename,
        title=title or _default_title(filename),
        content=text,
        metadata_={"parse_kind": kind, "original_filename": filename},
        folder_path=normalized_path,
        created_by=created_by,
        status="pending",
        progress=0,
    )
    db.add(doc)
    await db.flush()
    # 提交使 pending 行对轮询可见；后台任务用独立 session 续做
    await db.commit()
    await db.refresh(doc)

    coll_id = str(coll.id)
    doc_id = str(doc.id)
    org_id_str = str(org_id)
    asyncio.create_task(_run_ingest_bg(doc_id, coll_id, org_id_str))
    return doc


def _default_title(filename: str) -> str:
    name = filename.strip()
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name or "未命名文档"


async def _ensure_folder_chain(
    db: AsyncSession, coll: RagCollection, path: str, created_by: str | None = None,
) -> None:
    """为 ``path`` 的每一级前缀补建 RagFolder（幂等）。

    ``create_folder`` 按 (collection_id, path) 去重，命中即返回，故逐级调用安全。
    用于文件夹上传：``myfolder/sub`` → 建 ``myfolder`` 与 ``myfolder/sub``。
    """
    normalized = _normalize_path(path)
    if not normalized:
        return
    prefix = ""
    for seg in normalized.split("/"):
        prefix = f"{prefix}/{seg}" if prefix else seg
        await create_folder(db, coll, RagFolderCreate(path=prefix), created_by=created_by)


async def _run_ingest_bg(doc_id: str, coll_id: str, org_id: str) -> None:
    """后台入库任务：自带 session，分阶段更新 status/progress。

    阶段：parsing(5) → chunking(10) → embedding(10..95，按批递增) → ready(100)。
    任何异常置 ``failed`` 并写 ``parse_error``。文本已在请求线程落库为 doc.content，
    故即使本任务异常，文档内容仍在，可经「编辑分块/重新入库」恢复。
    """
    try:
        async with async_session_factory() as db:
            doc = await get_document(db, UUID(doc_id))
            if doc is None:
                logger.warning("rag_bg_doc_missing", doc_id=doc_id)
                return
            coll = await get_collection(db, UUID(coll_id))
            if coll is None:
                doc.status = "failed"
                doc.parse_error = "所属知识库不存在"
                doc.progress = 0
                await db.commit()
                return

            doc.status = "parsing"
            doc.progress = 5
            await db.commit()

            chunks = _split_text(doc.content or "", coll.chunk_size, coll.chunk_overlap)

            doc.status = "chunking"
            doc.progress = 10
            await db.commit()

            async def _p(done: int, total: int) -> None:
                # 嵌入阶段占 10..95，逐批提交使前端轮询可见递增
                doc.progress = 10 + int(85 * (done / total)) if total else 95
                await db.commit()

            await _chunk_and_embed(
                db, doc, coll, UUID(org_id), chunks, on_progress=_p,
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — 后台任务兜底：置失败，不抛出（否则无捕获）
        logger.warning("rag_ingest_bg_failed", doc_id=doc_id, error=str(exc))
        try:
            async with async_session_factory() as db:
                doc = await get_document(db, UUID(doc_id))
                if doc is not None:
                    doc.status = "failed"
                    doc.parse_error = str(exc)[:1000]
                    doc.progress = 0
                    await db.commit()
        except Exception:  # noqa: BLE001
            pass


async def get_document_status(db: AsyncSession, doc_id: UUID) -> RagDocumentStatusRead | None:
    """文档入库状态（前端轮询用）。"""
    doc = await get_document(db, doc_id)
    if doc is None:
        return None
    count = (await db.execute(
        select(func.count()).select_from(RagChunk).where(RagChunk.document_id == doc.id)
    )).scalar_one()
    return RagDocumentStatusRead(
        id=doc.id,
        status=doc.status,
        progress=doc.progress,
        parse_error=doc.parse_error,
        chunk_count=int(count or 0),
    )


async def list_documents(db: AsyncSession, coll_id: UUID, folder_path: str | None = None) -> list[RagDocument]:
    """列出集合文档；指定 folder_path 时仅返回该文件夹直接下属文档。

    folder_path 为空串或 None 表示根目录；此时排除 folder_path 非空的文档。
    """
    stmt = select(RagDocument).where(RagDocument.collection_id == coll_id, RagDocument.deleted_at.is_(None))
    if folder_path is not None:
        normalized = _normalize_path(folder_path)
        if normalized == "":
            stmt = stmt.where(RagDocument.folder_path == "")
        else:
            stmt = stmt.where(RagDocument.folder_path == normalized)
    return list((await db.execute(stmt)).scalars().all())


async def get_document(db: AsyncSession, doc_id: UUID) -> RagDocument | None:
    result = await db.execute(
        select(RagDocument).where(RagDocument.id == doc_id, RagDocument.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_document(db: AsyncSession, doc: RagDocument, data: RagDocumentUpdate) -> RagDocument:
    """文档重命名 / 移动。"""
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "folder_path" and value is not None:
            value = _normalize_path(value)
        setattr(doc, field, value)
    await db.flush()
    await db.refresh(doc)
    return doc


async def soft_delete_document(db: AsyncSession, doc: RagDocument) -> None:
    """软删文档（其分块 RagChunk 无 deleted_at 列，沿用既有策略不级联）。"""
    doc.deleted_at = datetime.now(UTC)
    await db.flush()


async def list_chunks(db: AsyncSession, doc_id: UUID) -> list[RagChunk]:
    """列出文档的分块，按 chunk_index 排序（chunk_index 存于 metadata_）。"""
    rows = (await db.execute(
        select(RagChunk).where(RagChunk.document_id == doc_id)
    )).scalars().all()
    rows.sort(key=lambda c: c.metadata_.get("chunk_index", 0) if isinstance(c.metadata_, dict) else 0)
    return rows


async def reingest_document(
    db: AsyncSession, doc: RagDocument, org_id: UUID, data: RagReingestRequest,
) -> RagDocument:
    """按分块重新入库：替换原分块并重新嵌入，保留同一文档 id。

    - ``data.chunks`` 非空：以用户在「分块编辑」视图里编辑的分块边界为准，直接落库；
      ``doc.content`` 同步为分块拼接结果。
    - ``data.chunks`` 为 ``None``：「从原文重切」——用当前结构感知分块器对 ``doc.content``
      按 ``coll.chunk_size/overlap`` 重新切分，用于已入库文档在分块算法改进后刷新分块，
      无需重新上传文件。
    """
    coll = await get_collection(db, doc.collection_id)
    if data.source is not None:
        doc.source = data.source
    if data.title is not None:
        doc.title = data.title
    if data.folder_path is not None:
        doc.folder_path = _normalize_path(data.folder_path)

    # 删除旧分块（RagChunk 无软删列，物理删除）
    await db.execute(delete(RagChunk).where(RagChunk.document_id == doc.id))

    if data.chunks is None:
        # 从原文重切：用最新分块器（结构感知）重新切分 doc.content
        chunks = _split_text(doc.content or "", coll.chunk_size, coll.chunk_overlap)
        # doc.content 保持原文不变（重切不改变源文本）
    else:
        chunks = [c for c in data.chunks if c.strip()]
        doc.content = "\n\n".join(chunks)

    # embedding 是入库契约的一部分：失败即 raise，让事务回滚——旧分块已在上面 delete
    # （仅 flush 未 commit），回滚后旧 chunk 与原 doc 恢复，不留下 0 chunk 的 failed 行。
    try:
        vectors = await llm_client.embed(db, org_id, coll.embedding_model, chunks)
    except Exception as exc:  # noqa: BLE001
        raise EmbeddingError(str(exc)) from exc
    if not vectors or len(vectors) != len(chunks):
        got = len(vectors) if vectors else 0
        raise EmbeddingError(f"embedding 返回向量数 {got} 与 chunk 数 {len(chunks)} 不符")

    for idx, (text, vec) in enumerate(zip(chunks, vectors, strict=False)):
        db.add(RagChunk(
            collection_id=coll.id,
            document_id=doc.id,
            content=text,
            embedding=vec,
            metadata_={"chunk_index": idx},
        ))
    await db.flush()
    await db.refresh(doc)
    return doc


# ── Folders ────────────────────────────────────────────────────────────

def _normalize_path(path: str) -> str:
    """规范化相对路径，防止越权（剥离前导 / 与 .. 段）。"""
    parts: list[str] = []
    for seg in path.replace("\\", "/").split("/"):
        if seg in ("", ".",):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


async def create_folder(
    db: AsyncSession, coll: RagCollection, data: RagFolderCreate, created_by: str | None = None,
) -> RagFolder:
    """新建文件夹（幂等）：path 规范化后按 (collection_id, path) 去重。

    命中已存在记录时直接返回（不覆盖原 ``created_by``，避免「夺走」他人创建的文件夹归属）；
    仅真正新建时才写入 ``created_by``。"""
    path = _normalize_path(data.path)
    result = await db.execute(
        select(RagFolder).where(
            RagFolder.collection_id == coll.id,
            RagFolder.path == path,
            RagFolder.deleted_at.is_(None),
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        folder = RagFolder(collection_id=coll.id, path=path, created_by=created_by)
        db.add(folder)
        await db.flush()
        await db.refresh(folder)
    return folder


async def list_folders(db: AsyncSession, coll_id: UUID, parent: str | None = None) -> list[RagFolder]:
    """列出集合文件夹；指定 parent 时仅返回该文件夹直接子文件夹（一层）。"""
    stmt = select(RagFolder).where(
        RagFolder.collection_id == coll_id, RagFolder.deleted_at.is_(None)
    ).order_by(RagFolder.path)
    folders = list((await db.execute(stmt)).scalars().all())
    if parent is None:
        return folders
    normalized = _normalize_path(parent)
    # 直接子文件夹：path 以 ``parent/`` 开头，且去掉前缀后只剩单段（无再下一层 /）
    direct: list[RagFolder] = []
    prefix = f"{normalized}/" if normalized else ""
    for f in folders:
        if not prefix:
            # 根下直接子：path 不含 /
            if "/" not in f.path:
                direct.append(f)
        else:
            if f.path.startswith(prefix):
                rest = f.path[len(prefix):]
                if rest and "/" not in rest:
                    direct.append(f)
    return direct


async def get_folder(db: AsyncSession, folder_id: UUID) -> RagFolder | None:
    result = await db.execute(
        select(RagFolder).where(RagFolder.id == folder_id, RagFolder.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def rename_folder(db: AsyncSession, folder: RagFolder, data: RagFolderUpdate) -> RagFolder:
    """重命名 / 移动文件夹，并同步其后代文件夹与所属文档的 path 前缀。"""
    old_path = folder.path
    new_path = _normalize_path(data.path)
    if old_path == new_path:
        return folder
    now = datetime.now(UTC)
    old_prefix = f"{old_path}/"
    new_prefix = f"{new_path}/" if new_path else ""

    # 后代文件夹：替换前缀
    sub_folders = (await db.execute(
        select(RagFolder).where(
            RagFolder.collection_id == folder.collection_id,
            RagFolder.path.startswith(old_prefix),
            RagFolder.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_folders:
        sf.path = new_prefix + sf.path[len(old_prefix):]
        sf.updated_at = now  # type: ignore[assignment]

    # 该文件夹及其后代下的文档：folder_path == old_path 或以 old_prefix 开头
    docs = (await db.execute(
        select(RagDocument).where(
            RagDocument.collection_id == folder.collection_id,
            RagDocument.deleted_at.is_(None),
        )
    )).scalars().all()
    for doc in docs:
        if doc.folder_path == old_path:
            doc.folder_path = new_path
            doc.updated_at = now  # type: ignore[assignment]
        elif doc.folder_path.startswith(old_prefix):
            doc.folder_path = new_prefix + doc.folder_path[len(old_prefix):]
            doc.updated_at = now  # type: ignore[assignment]

    folder.path = new_path
    folder.updated_at = now  # type: ignore[assignment]
    await db.flush()
    await db.refresh(folder)
    return folder


async def soft_delete_folder(db: AsyncSession, folder: RagFolder) -> None:
    """软删文件夹 + 其下所有子文件夹 + 该前缀下所有文档（级联）。

    嵌套靠路径段，故以 ``folder.path + "/"`` 前缀匹配后代与文档。
    """
    now = datetime.now(UTC)
    prefix = f"{folder.path}/"

    # 子文件夹
    sub_folders = (await db.execute(
        select(RagFolder).where(
            RagFolder.collection_id == folder.collection_id,
            RagFolder.path.startswith(prefix),
            RagFolder.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_folders:
        sf.deleted_at = now  # type: ignore[assignment]

    # 该文件夹自身 + 前缀下文档
    docs = (await db.execute(
        select(RagDocument).where(
            RagDocument.collection_id == folder.collection_id,
            RagDocument.deleted_at.is_(None),
        )
    )).scalars().all()
    for doc in docs:
        if doc.folder_path == folder.path or doc.folder_path.startswith(prefix):
            doc.deleted_at = now  # type: ignore[assignment]

    folder.deleted_at = now
    await db.flush()


# ── Ingest config (organization-level defaults) ───────────────────────

_INGEST_DEFAULTS = RagIngestConfig()


async def get_ingest_config(db: AsyncSession, org_id: UUID) -> RagIngestConfig:
    """读取组织级默认入库参数（存于 organization.settings['rag_ingest_defaults']）。"""
    org = await _get_org(db, org_id)
    raw = (org.settings or {}).get("rag_ingest_defaults", {})
    # 用默认值补全缺失字段，保证返回结构稳定
    merged = _INGEST_DEFAULTS.model_dump()
    merged.update(raw or {})
    return RagIngestConfig(**merged)


async def set_ingest_config(db: AsyncSession, org_id: UUID, data: RagIngestConfig) -> RagIngestConfig:
    """写入组织级默认入库参数。只更新 rag_ingest_defaults 键，保留 settings 其它键。"""
    org = await _get_org(db, org_id)
    settings = dict(org.settings or {})
    settings["rag_ingest_defaults"] = data.model_dump()
    org.settings = settings  # type: ignore[assignment]
    await db.flush()
    return data


async def _get_org(db: AsyncSession, org_id: UUID) -> Organization:
    org = (await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    )).scalar_one_or_none()
    if org is None:
        raise RuntimeError(f"organization {org_id} not found")
    return org


# ── Retrieval ──────────────────────────────────────────────────────────

_CJK_RUN_RE = re.compile(r"[一-鿿]{2,}")


def _cjk_ngrams(text: str, ns: tuple[int, ...] = (2, 3)) -> set[str]:
    """从中文片段提取 2/3 字 n-gram，供无向量时的关键词兜底检索。

    pg_trgm 的 ``similarity`` 对 CJK 默认按非词字符处理（恒为 0）、tsvector 对未分词
    中文亦不可用；故此处用字符级 n-gram + 子串匹配——query 含「请假」即可命中
    「员工考勤与请假管理制度」。
    """
    grams: set[str] = set()
    for run in _CJK_RUN_RE.findall(text or ""):
        for n in ns:
            for i in range(len(run) - n + 1):
                grams.add(run[i:i + n])
    return grams


async def _keyword_retrieve(
    db: AsyncSession, coll: RagCollection, req: RagRetrieveRequest,
) -> list[dict]:
    """向量不可用时的兜底：按 query 的 CJK n-gram 子串匹配 chunk，按命中 n-gram 数排序。

    score = 命中 n-gram 数 / query 总 n-gram 数（覆盖度）。命中的 ``metadata.retriever``
    记为 ``keyword_fallback`` 供调用方区分检索来源。
    """
    grams = _cjk_ngrams(req.query)
    if not grams:
        return []
    stmt = select(RagChunk.id, RagChunk.document_id, RagChunk.content).where(
        RagChunk.collection_id == coll.id,
    )
    rows = (await db.execute(stmt)).all()
    scored: list[tuple[int, object]] = []
    for r in rows:
        content = r.content or ""
        hits = sum(1 for g in grams if g in content)
        if hits:
            scored.append((hits, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "chunk_id": str(r.id),
            "document_id": str(r.document_id) if r.document_id else None,
            "content": r.content,
            "score": round(hits / len(grams), 4),
            "metadata": {"retriever": "keyword_fallback", "matches": hits},
        }
        for hits, r in scored[: req.top_k]
    ]


async def retrieve(
    db: AsyncSession,
    coll: RagCollection,
    org_id: UUID,
    req: RagRetrieveRequest,
) -> list[dict]:
    """检索 collection 命中。优先 pgvector 余弦检索；向量不可用或无命中时回退 CJK 关键词检索。

    - 向量命中：score = 1 - 余弦距离。
    - 关键词命中：score = 命中 n-gram 占比，``metadata.retriever='keyword_fallback'``。

    embedding 不可用（如组织未配 embedding provider）不再抛错，而是降级到关键词检索，
    保证 RAG 在无向量通道时仍可命中含查询关键词的文档。
    """
    # 1. 向量检索
    qvec = None
    try:
        qvecs = await llm_client.embed(db, org_id, coll.embedding_model, [req.query])
        if qvecs:
            qvec = qvecs[0]
    except Exception as exc:  # noqa: BLE001 — embedding 不可用时降级到关键词检索
        logger.warning("rag_embed_failed_fallback_keyword", collection=str(coll.id), error=str(exc))

    if qvec is not None:
        stmt = (
            select(
                RagChunk.id,
                RagChunk.document_id,
                RagChunk.content,
                RagChunk.embedding.cosine_distance(qvec).label("distance"),
                RagChunk.metadata_,
            )
            .where(
                RagChunk.collection_id == coll.id,
                RagChunk.embedding.is_not(None),
            )
            .order_by("distance")
            .limit(req.top_k)
        )
        rows = (await db.execute(stmt)).all()
        vec_hits = [
            {
                "chunk_id": str(r.id),
                "document_id": str(r.document_id) if r.document_id else None,
                "content": r.content,
                "score": 1.0 - float(r.distance),
                "metadata": r.metadata_,
            }
            for r in rows
        ]
        if vec_hits:
            return vec_hits

    # 2. 兜底：向量不可用 / 无向量命中 → CJK 关键词检索
    return await _keyword_retrieve(db, coll, req)
