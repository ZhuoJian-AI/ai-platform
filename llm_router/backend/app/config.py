"""Application configuration via Pydantic Settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Backend directory (where .env lives)
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "LLM Router"
    app_env: str = "development"
    debug: bool = False
    secret_key: str = "ai-infra-dev-secret-key-change-in-production"
    master_encryption_key: str = "zmE5st2H+zdf25a+oul6Ci8dEvLavTOdn+7j/ZH1Q1c="

    # Database (Docker PostgreSQL on port 5434)
    database_url: str = "postgresql+asyncpg://ai_infra:ai_infra@localhost:5434/ai_infra"

    # Redis (Docker Redis on port 6381)
    redis_url: str = "redis://localhost:6381/0"

    # Executable Skill runner (internal network only)
    code_skills_enabled: bool = False
    agent_skills_org_allowlist: str = ""
    skill_runner_url: str = "http://localhost:8020"
    skill_runner_token: str = "skill-runner-dev-token-change-in-production"
    skill_runner_timeout_seconds: int = 120
    skill_runner_queue_wait_seconds: int = 300
    skill_package_max_bytes: int = 100 * 1024 * 1024
    skill_package_expanded_max_bytes: int = 500 * 1024 * 1024
    skill_package_max_files: int = 1000
    storage_lifecycle_interval_seconds: int = 60 * 60
    storage_orphan_grace_days: int = 7

    # Single coordinator runtime (Docker-internal only).
    dsh_runtime_url: str = "http://localhost:8030"
    dsh_runtime_token: str = "dsh-runtime-dev-token-change-in-production"
    dsh_runtime_timeout_seconds: int = 600
    # Redis-backed DSH admission control shared by all Backend replicas.
    agent_global_concurrency: int = 12
    agent_user_concurrency: int = 2
    agent_queue_max: int = 100
    agent_queue_wait_seconds: int = 300
    agent_lease_seconds: int = 60
    agent_heartbeat_seconds: int = 15
    # Per-run model-step budget. Admission control remains the concurrency
    # guard; this budget only prevents a genuinely looping agent from running
    # forever. Complex office tasks need more than the old hard-coded 8 steps.
    agent_max_steps: int = 24
    extension_builder_url: str = "http://localhost:8040"
    extension_builder_token: str = "extension-builder-dev-token-change-in-production"
    extension_builder_timeout_seconds: int = 600
    extension_archive_max_bytes: int = 25 * 1024 * 1024
    extension_artifact_max_bytes: int = 100 * 1024 * 1024
    extension_catalog_community_url: str = "https://awesome-dsh-plugin.com/plugins.json"
    extension_catalog_sync_timeout_seconds: int = 90
    extension_catalog_sync_interval_seconds: int = 24 * 60 * 60
    extension_catalog_sync_poll_seconds: int = 60 * 60
    subsystem_sync_poll_seconds: int = 30
    # GitHub App-backed enterprise module repository publisher. The private
    # key is held only by the central backend; tenant ECS instances receive
    # repository-scoped, short-lived installation tokens.
    github_module_publisher_enabled: bool = False
    github_module_publisher_owner: str = "ZhuoJian-AI"
    github_module_publisher_app_id: str = ""
    github_module_publisher_installation_id: str = ""
    github_module_publisher_private_key_b64: str = ""
    github_module_publisher_timeout_seconds: int = 20
    # Central Coolify control plane.  The bearer token never leaves this
    # backend; tenant publish keys can only operate on their own deployment
    # profile and deterministic repository/domain names.
    coolify_module_deployer_enabled: bool = False
    coolify_api_url: str = ""
    coolify_api_token: str = ""
    coolify_timeout_seconds: int = 30
    module_saas_origin: str = "https://ai-platform.staging.zhuojianai.com"
    original_preview_enabled: bool = False
    # Native file preview is part of the staging-wide workspace experience;
    # keep the emergency deployment switch but no tenant allowlist.
    original_preview_org_allowlist: str = ""
    multimodal_vision_enabled: bool = True
    multimodal_vision_org_allowlist: str = "aifabei"
    image_generation_enabled: bool = True
    image_generation_org_allowlist: str = "aifabei"
    model_gateway_enabled: bool = True
    model_gateway_org_allowlist: str = "aifabei"
    multimodal_audio_enabled: bool = False
    multimodal_audio_org_allowlist: str = "aifabei"
    multimodal_user_concurrency: int = 2
    multimodal_daily_audio_seconds: int = 2 * 60 * 60
    multimodal_worker_poll_seconds: float = 1.0
    multimodal_worker_lease_seconds: int = 10 * 60
    multimodal_audio_max_bytes: int = 100 * 1024 * 1024

    # Workspace binary object storage (authorized ZhuoJian Storage Gateway).
    # Text workspace files stay inline for editing; Office/PDF/images use this
    # gateway when enabled.  No OSS AccessKey is held by this application.
    workspace_object_storage_enabled: bool = False
    storage_gateway_url: str = ""
    storage_project_token: str = ""
    storage_public_endpoint: str = ""
    storage_internal_endpoint: str = ""
    storage_accelerate_endpoint: str = ""
    storage_gateway_timeout_seconds: int = 60
    # Staging-wide workspace upload policy. It intentionally has no tenant
    # allowlist: every organization follows the same capability and limits.
    workspace_hybrid_upload_enabled: bool = True
    workspace_max_file_bytes: int = 5 * 1024 * 1024 * 1024
    workspace_ai_parse_max_bytes: int = 100 * 1024 * 1024
    workspace_proxy_upload_max_bytes: int = 1 * 1024 * 1024
    workspace_upload_session_ttl_seconds: int = 15 * 60
    workspace_trash_retention_days: int = 30

    @property
    def workspace_object_storage_configured(self) -> bool:
        return bool(
            self.workspace_object_storage_enabled
            and self.storage_gateway_url.strip()
            and self.storage_project_token.strip()
        )

    @property
    def github_module_publisher_configured(self) -> bool:
        return bool(
            self.github_module_publisher_enabled
            and self.github_module_publisher_owner.strip()
            and self.github_module_publisher_app_id.strip()
            and self.github_module_publisher_installation_id.strip()
            and self.github_module_publisher_private_key_b64.strip()
        )

    @property
    def coolify_module_deployer_configured(self) -> bool:
        return bool(
            self.coolify_module_deployer_enabled
            and self.coolify_api_url.strip()
            and self.coolify_api_token.strip()
        )

    def original_preview_enabled_for(self, organization_slug: str) -> bool:
        if not self.original_preview_enabled:
            return False
        allowed = {
            value.strip().lower()
            for value in self.original_preview_org_allowlist.split(",")
            if value.strip()
        }
        return not allowed or organization_slug.lower() in allowed

    def agent_skills_enabled_for(
        self,
        organization_slug: str,
        *,
        organization_id: object | None = None,
    ) -> bool:
        """Gate the new Agent Skill host independently per staging tenant."""
        if not self.code_skills_enabled:
            return False
        allowed = {
            value.strip().lower()
            for value in self.agent_skills_org_allowlist.split(",")
            if value.strip()
        }
        identities = {organization_slug.lower()}
        if organization_id is not None:
            identities.add(str(organization_id).lower())
        return not allowed or bool(allowed & identities)

    @staticmethod
    def _org_feature_enabled(
        enabled: bool,
        allowlist: str,
        organization_slug: str,
        *,
        organization_id: object | None = None,
    ) -> bool:
        if not enabled:
            return False
        allowed = {value.strip().lower() for value in allowlist.split(",") if value.strip()}
        identities = {organization_slug.lower()}
        if organization_id is not None:
            identities.add(str(organization_id).lower())
        return not allowed or bool(allowed & identities)

    def multimodal_vision_enabled_for(
        self, organization_slug: str, *, organization_id: object | None = None
    ) -> bool:
        return self._org_feature_enabled(
            self.multimodal_vision_enabled,
            self.multimodal_vision_org_allowlist,
            organization_slug,
            organization_id=organization_id,
        )

    def image_generation_enabled_for(
        self, organization_slug: str, *, organization_id: object | None = None
    ) -> bool:
        return self._org_feature_enabled(
            self.image_generation_enabled,
            self.image_generation_org_allowlist,
            organization_slug,
            organization_id=organization_id,
        )

    def model_gateway_enabled_for(
        self, organization_slug: str, *, organization_id: object | None = None
    ) -> bool:
        return self._org_feature_enabled(
            self.model_gateway_enabled,
            self.model_gateway_org_allowlist,
            organization_slug,
            organization_id=organization_id,
        )

    def multimodal_audio_enabled_for(
        self, organization_slug: str, *, organization_id: object | None = None
    ) -> bool:
        return self._org_feature_enabled(
            self.multimodal_audio_enabled,
            self.multimodal_audio_org_allowlist,
            organization_slug,
            organization_id=organization_id,
        )

    # API Key cache
    api_key_cache_ttl: int = 60

    # DLP Stream Scanner
    dlp_stream_buffer_window: int = 4096
    dlp_stream_flush_timeout_ms: int = 200

    # DLP：拦截时是否在错误响应中返回命中规则详情（规则名/严重级/脱敏命中片段）。
    # 便于调用方排查；生产环境若不想暴露规则名可置为 False。
    dlp_expose_matches_in_error: bool = True

    # 对外暴露的代理 Base URL（接入指引中展示给调用方）。
    # 部署并测通后按实际情况在 .env 中配置，例如 https://api.example.com
    # 留空时前端回退到当前站点 origin。
    proxy_base_url: str | None = None

    @property
    def normalized_proxy_base_url(self) -> str | None:
        """去掉末尾斜杠后的代理 Base URL，便于前端按需拼接 /v1。"""
        if not self.proxy_base_url:
            return None
        return self.proxy_base_url.rstrip("/")

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


settings = Settings()
