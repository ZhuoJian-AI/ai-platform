"""Schemas for provider credentials, model deployments and verification."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.multimodal_service import validate_provider_config

VENDORS = {"openai", "anthropic", "azure_openai", "aliyun_bailian", "volcengine_ark", "xiaomi_mimo", "custom"}
PROVIDER_TYPES = {"anthropic", "openai", "azure_openai", "custom"}
CAPABILITIES = {
    "chat", "vision", "embedding", "image_generation", "audio_understanding",
    "speech_to_text", "text_to_speech", "voice_design", "voice_clone",
}
ADAPTERS = {
    "openai_chat_completions", "openai_responses", "anthropic_messages",
    "openai_embeddings", "openai_images", "bailian_multimodal_generation", "volcengine_images",
    "openai_audio_transcription_chat", "openai_audio_synthesis_chat",
}


class ModelDeploymentCreate(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=255)
    display_name: str | None = Field(None, max_length=255)
    adapter: str = "openai_chat_completions"
    capabilities: list[str] = Field(default_factory=lambda: ["chat"])
    base_url_override: str | None = None
    endpoint_path: str | None = None
    embedding_dimensions: int | None = Field(None, gt=0)
    routing_priority: int = 0
    is_active: bool = True
    config: dict = Field(default_factory=dict)

    @field_validator("base_url_override")
    @classmethod
    def validate_base_url_override(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        from app.services.llm_provider_service import _validate_base_url
        return _validate_base_url(value)

    @model_validator(mode="after")
    def validate_adapter_capabilities(self):
        self.model_id = self.model_id.strip()
        if self.adapter not in ADAPTERS:
            raise ValueError(f"unsupported model adapter: {self.adapter}")
        normalized = list(dict.fromkeys(self.capabilities))
        if not normalized or not set(normalized).issubset(CAPABILITIES):
            raise ValueError("unsupported model capability")
        if "vision" in normalized and "chat" not in normalized:
            raise ValueError("vision deployments must also declare chat")
        if self.adapter == "anthropic_messages" and ({"embedding", "image_generation"} & set(normalized)):
            raise ValueError("Anthropic Messages does not provide embedding or image generation")
        if self.adapter in {"openai_chat_completions", "openai_responses"} and not set(normalized).issubset(
            {"chat", "vision", "audio_understanding"}
        ):
            raise ValueError("chat adapters only support chat, vision and audio understanding")
        if self.adapter == "openai_embeddings" and normalized != ["embedding"]:
            raise ValueError("openai_embeddings deployments must only declare embedding")
        if self.adapter in {"openai_images", "bailian_multimodal_generation", "volcengine_images"}:
            if normalized != ["image_generation"]:
                raise ValueError("image adapters must only declare image_generation")
        if self.adapter == "openai_audio_transcription_chat" and normalized != ["speech_to_text"]:
            raise ValueError("audio transcription adapter must only declare speech_to_text")
        if self.adapter == "openai_audio_synthesis_chat" and not set(normalized).issubset(
            {"text_to_speech", "voice_design", "voice_clone"}
        ):
            raise ValueError("audio synthesis adapter has incompatible capabilities")
        if self.endpoint_path:
            path = self.endpoint_path.strip()
            if not path.startswith("/") or "://" in path or ".." in path:
                raise ValueError("endpoint_path must be a safe relative path")
            self.endpoint_path = path
        self.capabilities = normalized
        return self


class ModelDeploymentUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=255)
    adapter: str | None = None
    capabilities: list[str] | None = None
    base_url_override: str | None = None
    endpoint_path: str | None = None
    embedding_dimensions: int | None = Field(None, gt=0)
    routing_priority: int | None = None
    is_active: bool | None = None
    config: dict | None = None

    @field_validator("base_url_override")
    @classmethod
    def validate_base_url_override(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        from app.services.llm_provider_service import _validate_base_url
        return _validate_base_url(value)


class ModelDeploymentRead(BaseModel):
    id: UUID
    provider_id: UUID
    model_id: str
    display_name: str | None
    adapter: str
    capabilities: list[str]
    base_url_override: str | None
    endpoint_path: str | None
    embedding_dimensions: int | None
    routing_priority: int
    is_active: bool
    verification_status: str
    last_error: str | None
    config: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LlmProviderCreate(BaseModel):
    name: str = Field(..., max_length=255)
    vendor: str = "custom"
    provider_type: str = "openai"
    region: str | None = None
    workspace_id: str | None = None
    access_mode: str = "payg"
    base_url: str | None = None
    api_key: str = Field(..., min_length=1)
    priority: int = 0
    weight: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=120, ge=10)
    max_retries: int = Field(default=2, ge=0)
    supported_models: list[str] = Field(default_factory=list)
    model_deployments: list[ModelDeploymentCreate] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    scope_type: str = Field(default="organization", pattern=r"^(organization|department|team)$")

    @model_validator(mode="after")
    def validate_provider(self):
        if self.vendor not in VENDORS:
            raise ValueError(f"unsupported vendor: {self.vendor}")
        if self.provider_type not in PROVIDER_TYPES:
            raise ValueError(f"unsupported provider_type: {self.provider_type}")
        if self.vendor in {"aliyun_bailian", "volcengine_ark"} and self.access_mode != "payg":
            raise ValueError("SaaS backend providers must use pay-as-you-go API credentials")
        if self.vendor in {"aliyun_bailian", "volcengine_ark"} and not self.region:
            self.region = "cn-beijing"
        if self.vendor == "xiaomi_mimo":
            self.region = self.region or "cn"
        return self

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict) -> dict:
        return validate_provider_config(value)


class LlmProviderUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    region: str | None = None
    workspace_id: str | None = None
    access_mode: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    is_active: bool | None = None
    priority: int | None = None
    weight: int | None = Field(None, ge=1)
    timeout_seconds: int | None = Field(None, ge=10)
    max_retries: int | None = Field(None, ge=0)
    supported_models: list[str] | None = None
    config: dict | None = None

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict | None) -> dict | None:
        return None if value is None else validate_provider_config(value)


class LlmProviderRead(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    vendor: str
    provider_type: str
    region: str | None
    workspace_id: str | None
    scope_type: str
    department_id: UUID | None = None
    team_id: UUID | None = None
    base_url: str
    api_key_masked: str = "••••••••"
    api_key_version: int
    is_active: bool
    priority: int
    weight: int
    timeout_seconds: int
    max_retries: int
    supported_models: list[str]
    health_status: str
    config: dict
    model_deployments: list[ModelDeploymentRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProviderConnectionTestRead(BaseModel):
    status: str
    vendor: str
    detail: str


class ModelCapabilityTestRead(BaseModel):
    status: str
    capability: str
    model_id: str
    detail: str
