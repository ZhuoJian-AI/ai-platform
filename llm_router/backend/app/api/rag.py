"""RAG CRUD + ingest + retrieval + folders + ingest-config API."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import (
    CurrentAdmin,
    assert_org_access,
    assert_org_write_access,
    require_admin,
    require_org_access,
    require_org_access_write,
)
from app.database import get_db
from app.schemas.rag import (
    RagChunkRead,
    RagCollectionCreate,
    RagCollectionRead,
    RagCollectionUpdate,
    RagDocumentCreate,
    RagDocumentRead,
    RagDocumentStatusRead,
    RagDocumentUpdate,
    RagFolderCreate,
    RagFolderRead,
    RagFolderUpdate,
    RagIngestConfig,
    RagReingestRequest,
    RagRetrieveRequest,
    RagRetrieveResponse,
)
from app.services import doc_parser
from app.services.rag_service import (
    create_collection,
    EmbeddingError,
    create_folder,
    get_collection,
    get_document,
    get_document_status,
    get_folder,
    get_ingest_config,
    ingest_document,
    ingest_uploaded_file,
    list_chunks,
    list_collections,
    list_documents,
    list_folders,
    reingest_document,
    rename_folder,
    retrieve,
    set_ingest_config,
    soft_delete_collection,
    soft_delete_document,
    soft_delete_folder,
    update_collection,
    update_document,
)

router = APIRouter()


# ── Collection ──

@router.post("/organizations/{org_id}/rag", response_model=RagCollectionRead, status_code=201)
async def create_coll_endpoint(
    org_id: UUID, data: RagCollectionCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    try:
        return await create_collection(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists")


@router.get("/organizations/{org_id}/rag", response_model=list[RagCollectionRead])
async def list_coll_endpoint(
    org_id: UUID,
    scope_type: str | None = Query(default=None, description="organization/department/team/user"),
    scope_id: str | None = Query(default=None),
    _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await list_collections(db, org_id, scope_type=scope_type, scope_id=scope_id)


@router.get("/rag/{coll_id}", response_model=RagCollectionRead)
async def get_coll_endpoint(
    coll_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_access(auth, coll.organization_id)
    return coll


@router.patch("/rag/{coll_id}", response_model=RagCollectionRead)
async def update_coll_endpoint(
    coll_id: UUID, data: RagCollectionUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    return await update_collection(db, coll, data)


@router.delete("/rag/{coll_id}", status_code=204)
async def delete_coll_endpoint(
    coll_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    await soft_delete_collection(db, coll)


# ── Document ingest / update / delete ──

@router.post("/rag/{coll_id}/documents", response_model=RagDocumentRead, status_code=201)
async def ingest_document_endpoint(
    coll_id: UUID, data: RagDocumentCreate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    try:
        return await ingest_document(db, coll, coll.organization_id, data)
    except EmbeddingError as exc:
        # service 已置 doc=failed + flush；commit 落库 failed 供排查，转 502 给前端
        await db.commit()
        raise HTTPException(status_code=502, detail=f"文档入库失败：embedding 不可用 — {exc}") from exc


@router.post("/rag/{coll_id}/documents/upload", response_model=RagDocumentRead, status_code=201)
async def upload_document_endpoint(
    coll_id: UUID,
    file: UploadFile = File(..., description="待解析入库的文档（pdf/docx/xlsx/csv/txt/md/html）"),
    title: str | None = Form(default=None),
    folder_path: str = Form(default=""),
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """上传文件入库：请求内同步解析抽取文本并落库，分块+嵌入交后台任务异步进行。

    返回的文档 ``status='pending'``；前端轮询 ``GET /rag/documents/{id}/status``
    获取阶段化进度（parsing→chunking→embedding→ready/failed）。
    """
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    raw = await file.read()
    try:
        return await ingest_uploaded_file(
            db, coll, coll.organization_id,
            filename=file.filename or "upload.bin",
            content_type=file.content_type,
            raw=raw,
            title=title,
            folder_path=folder_path,
        )
    except doc_parser.UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/rag/documents/{doc_id}/status", response_model=RagDocumentStatusRead)
async def document_status_endpoint(
    doc_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """轮询文档解析入库状态（上传后前端按 ~1s 轮询至 ready/failed）。"""
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="RAG document not found")
    coll = await get_collection(db, doc.collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_access(auth, coll.organization_id)
    status = await get_document_status(db, doc.id)
    if status is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    return status


@router.get("/rag/{coll_id}/documents", response_model=list[RagDocumentRead])
async def list_documents_endpoint(
    coll_id: UUID,
    folder_path: str | None = Query(default=None, description="仅返回该文件夹直接下属文档；空串=根"),
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_access(auth, coll.organization_id)
    return await list_documents(db, coll.id, folder_path=folder_path)


@router.patch("/rag/documents/{doc_id}", response_model=RagDocumentRead)
async def update_document_endpoint(
    doc_id: UUID, data: RagDocumentUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="RAG document not found")
    coll = await get_collection(db, doc.collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    return await update_document(db, doc, data)


@router.delete("/rag/documents/{doc_id}", status_code=204)
async def delete_document_endpoint(
    doc_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="RAG document not found")
    coll = await get_collection(db, doc.collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    await soft_delete_document(db, doc)


# ── Document chunk edit / re-ingest ──

@router.get("/rag/documents/{doc_id}/chunks", response_model=list[RagChunkRead])
async def list_chunks_endpoint(
    doc_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="RAG document not found")
    coll = await get_collection(db, doc.collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_access(auth, coll.organization_id)
    chunks = await list_chunks(db, doc.id)
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


@router.post("/rag/documents/{doc_id}/reingest", response_model=RagDocumentRead)
async def reingest_document_endpoint(
    doc_id: UUID, data: RagReingestRequest,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """重新入库：替换原分块并重新嵌入。

    ``chunks`` 为分块列表时按编辑边界落库；为 ``null`` 时从 ``doc.content`` 用结构感知
    分块器重切（用于已入库文档刷新分块，无需重新上传）。
    """
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="RAG document not found")
    coll = await get_collection(db, doc.collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    try:
        return await reingest_document(db, doc, coll.organization_id, data)
    except EmbeddingError as exc:
        # 回滚：恢复旧分块与原 doc，不留下 0 chunk 的 failed 行
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"重新入库失败：embedding 不可用 — {exc}") from exc


# ── Folders ──

@router.post("/rag/{coll_id}/folders", response_model=RagFolderRead, status_code=201)
async def create_folder_endpoint(
    coll_id: UUID, data: RagFolderCreate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    return await create_folder(db, coll, data)


@router.get("/rag/{coll_id}/folders", response_model=list[RagFolderRead])
async def list_folders_endpoint(
    coll_id: UUID,
    parent: str | None = Query(default=None, description="仅返回该文件夹直接子文件夹；空串=根"),
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_access(auth, coll.organization_id)
    return await list_folders(db, coll.id, parent=parent)


@router.patch("/rag/folders/{folder_id}", response_model=RagFolderRead)
async def rename_folder_endpoint(
    folder_id: UUID, data: RagFolderUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    folder = await get_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="RAG folder not found")
    coll = await get_collection(db, folder.collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    try:
        return await rename_folder(db, folder, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="目标路径已存在同名文件夹")


@router.delete("/rag/folders/{folder_id}", status_code=204)
async def delete_folder_endpoint(
    folder_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    folder = await get_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="RAG folder not found")
    coll = await get_collection(db, folder.collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_write_access(auth, coll.organization_id)
    await soft_delete_folder(db, folder)


# ── Ingest config (organization-level defaults) ──

@router.get("/organizations/{org_id}/rag/ingest-config", response_model=RagIngestConfig)
async def get_ingest_config_endpoint(
    org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await get_ingest_config(db, org_id)


@router.put("/organizations/{org_id}/rag/ingest-config", response_model=RagIngestConfig)
async def set_ingest_config_endpoint(
    org_id: UUID, data: RagIngestConfig,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    return await set_ingest_config(db, org_id, data)


# ── Retrieval test ──

@router.post("/rag/{coll_id}/retrieve", response_model=RagRetrieveResponse)
async def retrieve_endpoint(
    coll_id: UUID, data: RagRetrieveRequest,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    coll = await get_collection(db, coll_id)
    if not coll:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    assert_org_access(auth, coll.organization_id)
    try:
        hits = await retrieve(db, coll, coll.organization_id, data)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return RagRetrieveResponse(query=data.query, hits=hits)
