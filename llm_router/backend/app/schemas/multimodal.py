"""Public contracts for durable audio jobs and enterprise voice governance."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AudioTranscriptionCreate(BaseModel):
    workspace_file_id: UUID
    language: Literal["auto", "zh", "en"] = "auto"
    model: str = "default"
    idempotency_key: str | None = Field(default=None, max_length=160)


class AudioUnderstandCreate(BaseModel):
    workspace_file_id: UUID
    question: str = Field(min_length=1, max_length=10_000)
    model: str = "default"


class SpeechCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    voice_profile_id: UUID
    style: str | None = Field(default=None, max_length=500)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: Literal["wav", "mp3", "pcm", "pcm16"] = "wav"
    model: str = "default"
    idempotency_key: str | None = Field(default=None, max_length=160)


class MultimodalJobRead(BaseModel):
    id: UUID
    organization_id: UUID
    user_id: UUID
    capability: str
    status: str
    request_id: str
    input_file_id: UUID | None
    output_url: str | None = None
    voice_profile_id: UUID | None
    result: dict
    usage: dict
    attempts: int
    audio_duration_ms: int | None
    latency_ms: int | None
    error_category: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class MultimodalJobCreated(BaseModel):
    job_id: UUID
    request_id: str
    status: str


VoiceType = Literal["builtin", "designed", "cloned"]
VoiceScopeType = Literal["organization", "role", "department", "user"]


class VoiceGrantInput(BaseModel):
    scope_type: VoiceScopeType
    scope_id: UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type == "organization" and self.scope_id is not None:
            raise ValueError("organization voice grants do not accept scope_id")
        if self.scope_type != "organization" and self.scope_id is None:
            raise ValueError("scope_id is required for scoped voice grants")
        return self


class VoiceBuiltinCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    provider_voice_id: str = Field(min_length=1, max_length=255)
    grants: list[VoiceGrantInput] = Field(default_factory=list)


class VoiceDesignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    design_prompt: str = Field(min_length=5, max_length=4000)
    grants: list[VoiceGrantInput] = Field(default_factory=list)


class VoiceCloneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    sample_file_id: UUID
    evidence_file_id: UUID
    rights_holder: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=4000)
    valid_until: datetime
    confirmed: bool
    grants: list[VoiceGrantInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_confirmation(self):
        if not self.confirmed:
            raise ValueError("voice clone requires explicit confirmation")
        return self


class VoiceProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["active", "disabled"] | None = None
    grants: list[VoiceGrantInput] | None = None


class VoiceGrantRead(BaseModel):
    id: UUID
    scope_type: str
    scope_id: str | None

    model_config = {"from_attributes": True}


class VoiceProfileRead(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    voice_type: str
    provider_voice_id: str | None
    design_prompt: str | None
    sample_file_id: UUID | None
    status: str
    config: dict
    grants: list[VoiceGrantRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AudioUnderstandingRead(BaseModel):
    content: str
    reasoning_content: str | None = None
    model: str
    usage: dict
    request_id: str
