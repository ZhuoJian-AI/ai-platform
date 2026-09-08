"""Employee-authenticated specialist AI requested through the embedded host bridge."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser, require_user
from app.config import settings
from app.database import get_db
from app.schemas.multimodal import SubsystemAiCapability, SubsystemAiRunCreated, SubsystemAiRunRead
from app.services import subsystem_ai_service as service

router = APIRouter(prefix="/subsystem-ai")


def _object_json(value: str, field: str) -> dict:
    if len(value.encode()) > 64 * 1024:
        raise HTTPException(status_code=422, detail=f"{field} 超过 64KB 限制")
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{field} 必须是 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail=f"{field} 必须是 JSON 对象")
    return parsed


@router.post("/runs", response_model=SubsystemAiRunCreated, status_code=202)
async def create_subsystem_ai_run(
    application_id: UUID = Form(...),
    module_key: str = Form(..., min_length=1, max_length=120),
    page_key: str = Form(..., min_length=1, max_length=160),
    action_key: str = Form(..., min_length=1, max_length=160),
    capability: SubsystemAiCapability = Form(...),
    instruction: str = Form(default="", max_length=4000),
    context_json: str = Form(default="{}"),
    text_input: str = Form(default="", max_length=100_000),
    request_id: str = Form(..., min_length=8, max_length=120),
    files: list[UploadFile] = File(default=[]),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if len(files) > settings.subsystem_ai_max_files:
        raise HTTPException(
            status_code=422,
            detail=f"每次最多上传 {settings.subsystem_ai_max_files} 个输入文件",
        )
    prepared = []
    total = 0
    for uploaded in files:
        remaining = settings.subsystem_ai_max_input_bytes - total
        raw = await uploaded.read(max(0, remaining) + 1)
        total += len(raw)
        if total > settings.subsystem_ai_max_input_bytes:
            raise HTTPException(status_code=413, detail="专业 AI 输入文件总大小超过平台限制")
        prepared.append(service.prepare_input(uploaded.filename or "input.bin", uploaded.content_type, raw))
    job = await service.create_run(
        db,
        user,
        application_id=application_id,
        module_key=module_key,
        page_key=page_key,
        action_key=action_key,
        capability=capability,
        instruction=instruction.strip(),
        context=_object_json(context_json, "context_json"),
        text_input=text_input,
        request_id=request_id,
        inputs=prepared,
    )
    return SubsystemAiRunCreated(run_id=job.id, request_id=job.request_id, status=job.status)


@router.get("/runs/{run_id}", response_model=SubsystemAiRunRead)
async def get_subsystem_ai_run(
    run_id: UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return service.run_payload(await service.require_visible_run(db, user, run_id))


@router.post("/runs/{run_id}/cancel", response_model=SubsystemAiRunRead)
async def cancel_subsystem_ai_run(
    run_id: UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return service.run_payload(await service.cancel_run(db, user, run_id))
