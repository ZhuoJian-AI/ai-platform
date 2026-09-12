"""Speech reads only server-published segments of an owned Run, never client text."""
import json
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.agents.graph import run_registry
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.task import Task
from app.models.user import User
from app.services import message_speech_service as speech


class RunSpeechCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    run_id: int = Field(gt=0)
    segment_index: int = Field(ge=0, le=63)
    expected_content_version: str = Field(pattern=r"^[0-9a-f]{64}$")


async def owned_events(db, cu, task_id: UUID, run_id: int):
    run = (await db.execute(select(AgentRun).join(Task, Task.id == AgentRun.task_id).where(
        AgentRun.id == run_id, Task.id == task_id, Task.user_id == UUID(cu.id),
        Task.organization_id == cu.organization_id, AgentRun.user_id == UUID(cu.id),
        AgentRun.organization_id == cu.organization_id, Task.deleted_at.is_(None),
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "本轮对话不存在或不属于当前用户")
    if run.status in {"cancelled", "timeout", "busy", "error"}:
        return [], True
    handle = run_registry.get(str(task_id))
    if handle is not None and handle.run_id == run_id:
        return [json.loads(raw) for raw in list(handle.buffer)], handle.done
    events = list((await db.execute(select(AgentRunEvent.payload).where(
        AgentRunEvent.run_id == run_id, AgentRunEvent.task_id == str(task_id),
    ).order_by(AgentRunEvent.seq))).scalars())
    return events, True  # No live producer: never poll indefinitely after a restart.


def select_segments(events):
    segments = {}
    for event in events:
        if event.get("type") == "speech_reset":
            segments.clear()
        elif event.get("type") == "speech_segment":
            index = event.get("segmentIndex")
            text = event.get("text")
            if isinstance(index, int) and 0 <= index < 64 and isinstance(text, str) and text:
                segments[index] = {"segment_index": index, "text": text,
                                   "content_version": speech.content_version(text)}
    return segments


async def owned_segment(db, cu, task_id, run_id, index):
    events, _ = await owned_events(db, cu, task_id, run_id)
    segment = select_segments(events).get(index)
    if segment is None:
        raise HTTPException(409, "本轮语音尚未就绪或已撤回")
    return segment


async def plan(db, cu, task_id: UUID, run_id: int):
    await speech.audio.require_multimodal_enabled(db, cu.organization_id)
    speech.audio.require_permission(cu, "multimodal.speech.use")
    events, done = await owned_events(db, cu, task_id, run_id)
    segments = select_segments(events)
    return {"run_id": run_id, "done": done, "segments": [
        {k: value for k, value in item.items() if k != "text"}
        for _, item in sorted(segments.items())]}


async def create(db, cu, data: RunSpeechCreate):
    await speech.audio.require_multimodal_enabled(db, cu.organization_id)
    speech.audio.require_permission(cu, "multimodal.speech.use")
    await db.execute(select(User.id).where(User.id == UUID(cu.id)).with_for_update())
    segment = await owned_segment(db, cu, data.task_id, data.run_id, data.segment_index)
    if segment["content_version"] != data.expected_content_version:
        raise HTTPException(409, "本轮语音已变化，请获取最新片段")
    return await speech.create_bound_speech(db, cu, segment["text"], {
        "task_id": str(data.task_id), "run_id": data.run_id,
        "segment_index": data.segment_index, "content_version": segment["content_version"],
    })
