"""Authenticated audio jobs and enterprise voice governance endpoints."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_admin
from app.auth.user_auth import CurrentUser, require_user
from app.database import get_db
from app.schemas.multimodal import (
    AudioTranscriptionCreate,
    AudioUnderstandCreate,
    MultimodalJobCreated,
    MultimodalJobRead,
    SpeechCreate,
    VoiceBuiltinCreate,
    VoiceCloneCreate,
    VoiceDesignCreate,
    VoiceProfileRead,
    VoiceProfileUpdate,
)
from app.services import multimodal_audio_service as service
from app.services.model_gateway import GatewayError, classify_gateway_error

router = APIRouter(prefix="/multimodal")


def _admin_org(auth: CurrentAdmin, organization_id: UUID | None) -> UUID:
    if auth.organization_id is not None:
        if organization_id is not None and organization_id != auth.organization_id:
            raise HTTPException(status_code=403, detail="No access to this organization")
        return auth.organization_id
    if organization_id is None:
        raise HTTPException(status_code=422, detail="organization_id is required for platform administrators")
    return organization_id


def _created(job) -> MultimodalJobCreated:
    return MultimodalJobCreated(job_id=job.id, request_id=job.request_id, status=job.status)


@router.post("/audio/transcriptions", response_model=MultimodalJobCreated, status_code=202)
async def create_transcription(
    data: AudioTranscriptionCreate,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return _created(await service.queue_transcription(db, cu, data))


@router.post("/audio/understand")
async def understand_audio(
    data: AudioUnderstandCreate,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    stream = await service.stream_understand_file(
        db, cu, data.workspace_file_id, data.question, data.model,
    )

    async def events():
        emitted_text = False
        try:
            async for event, payload, extra in stream:
                if event == "text" and payload:
                    emitted_text = True
                    body = {"content": str(payload)}
                    yield f"event: delta\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"
                elif event == "reasoning_content" and payload and not emitted_text:
                    # MiMo audio understanding may place its user-facing answer
                    # in reasoning_content while leaving content empty.
                    body = {"content": str(payload)}
                    yield f"event: delta\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"
                elif event == "usage":
                    yield f"event: usage\ndata: {json.dumps(extra or {}, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as exc:
            category = exc.category if isinstance(exc, GatewayError) else classify_gateway_error(exc)
            yield f"event: error\ndata: {json.dumps({'category': category})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/speech", response_model=MultimodalJobCreated, status_code=202)
async def create_speech(
    data: SpeechCreate,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return _created(await service.queue_speech(db, cu, data))


@router.get("/jobs/{job_id}", response_model=MultimodalJobRead)
async def get_job(
    job_id: UUID,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.job_read_payload(db, cu, job_id)


@router.get("/voices", response_model=list[VoiceProfileRead])
async def list_voices(
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_visible_voices(db, cu)


@router.get("/voice-admin", response_model=list[VoiceProfileRead])
async def list_admin_voices(
    organization_id: UUID | None = Query(default=None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_admin_voices(db, _admin_org(auth, organization_id), auth)


@router.post("/voices/builtin", response_model=VoiceProfileRead, status_code=201)
async def create_builtin_voice(
    data: VoiceBuiltinCreate,
    organization_id: UUID | None = Query(default=None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_builtin_voice(db, _admin_org(auth, organization_id), auth, data)


@router.post("/voices/design", response_model=VoiceProfileRead, status_code=201)
async def create_designed_voice(
    data: VoiceDesignCreate,
    organization_id: UUID | None = Query(default=None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_designed_voice(db, _admin_org(auth, organization_id), auth, data)


@router.post("/voices/clone", response_model=VoiceProfileRead, status_code=201)
async def create_cloned_voice(
    data: VoiceCloneCreate,
    organization_id: UUID | None = Query(default=None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_cloned_voice(db, _admin_org(auth, organization_id), auth, data)


@router.patch("/voices/{voice_id}", response_model=VoiceProfileRead)
async def update_voice(
    voice_id: UUID,
    data: VoiceProfileUpdate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_voice(db, voice_id, auth, data)


@router.delete("/voices/{voice_id}", status_code=204)
async def delete_voice(
    voice_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_voice(db, voice_id, auth)
    return Response(status_code=204)
