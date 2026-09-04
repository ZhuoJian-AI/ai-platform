"""Application configuration via Pydantic Settings."""

from pathlib import Path

from pydantic import SecretStr
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

    # Public OAuth/MCP boundary.  Production must set both URLs to the same
    # externally reachable HTTPS origin (for example https://infra.example.com).
    # Access tokens are deliberately short lived; refresh tokens rotate on
    # every use and have a separate absolute lifetime.
    oauth_issuer: str = ""
    oauth_public_base_url: str = ""
    oauth_signing_key: SecretStr = SecretStr("")
    oauth_access_token_minutes: int = 10
    oauth_authorization_code_seconds: int = 300
    oauth_refresh_token_days: int = 30
    oauth_refresh_token_absolute_days: int = 90
    oauth_dynamic_client_registration_enabled: bool = True
    oauth_dynamic_client_ttl_days: int = 180
    oauth_dynamic_client_limit_per_hour: int = 60
    oauth_dynamic_client_max_active: int = 5000
    browser_allowed_origins: str = ""
    # Comma-separated networks of reverse proxies that are allowed to supply
    # X-Forwarded-For.  Keep empty outside a controlled proxy deployment.
    trusted_proxy_cidrs: str = ""
    login_failure_limit: int = 10
    login_failure_window_seconds: int = 15 * 60

    # Database (Docker PostgreSQL on port 5434)
    database_url: str = "postgresql+asyncpg://ai_infra:ai_infra@localhost:5434/ai_infra"

    # Redis (Docker Redis on port 6381)
    redis_url: str = "redis://localhost:6381/0"
    # Every billable AI call must reserve hierarchical quota in Redis before
    # contacting a provider. Production is always fail-closed; this switch is
    # intentionally honored only in the development environment.
    ai_quota_development_fail_open: bool = True
    ai_quota_redis_timeout_seconds: float = 0.5
    ai_quota_default_max_output_tokens: int = 4096
    ai_quota_reservation_ttl_seconds: int = 40 * 24 * 60 * 60

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
    storage_project_token: SecretStr = SecretStr("")
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
    workspace_upload_session_ttl_seconds: int = 24 * 60 * 60
    workspace_weboffice_enabled: bool = False
    # Human-triggered Office editing is a separate fail-closed feature.  It is
    # never inferred from preview enablement: the Storage Gateway additionally
    # verifies IMM/MNS configuration and OSS versioning before issuing a token.
    workspace_weboffice_edit_enabled: bool = False
    workspace_office_event_callback_secret: SecretStr = SecretStr("")
    workspace_office_reconcile_poll_seconds: float = 1.0
    workspace_office_reconcile_lease_seconds: int = 5 * 60
    workspace_weboffice_max_bytes: int = 200 * 1024 * 1024
    workspace_pdf_direct_preview_max_bytes: int = 20 * 1024 * 1024
    workspace_preview_job_poll_seconds: float = 1.0
    workspace_preview_job_lease_seconds: int = 15 * 60
    workspace_trash_retention_days: int = 30

    @property
    def workspace_object_storage_configured(self) -> bool:
        return bool(
            self.workspace_object_storage_enabled
            and self.storage_gateway_url.strip()
            and self.storage_project_token_value
        )

    @property
    def storage_project_token_value(self) -> str:
        value = self.storage_project_token
        if isinstance(value, SecretStr):
            return value.get_secret_value().strip()
        # Tests and gradual configuration reloads may temporarily assign the
        # legacy plain-string representation.  Never expose it from repr/logs.
        return str(value or "").strip()

    @property
    def workspace_office_event_callback_secret_value(self) -> str:
        value = self.workspace_office_event_callback_secret
        if isinstance(value, SecretStr):
            return value.get_secret_value().strip()
        return str(value or "").strip()

    @property
    def workspace_weboffice_edit_configured(self) -> bool:
        """Fail closed unless every Platform-side editing dependency exists."""
        return bool(
            self.workspace_weboffice_edit_enabled
            and self.workspace_object_storage_configured
            and len(self.workspace_office_event_callback_secret_value) >= 32
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
    def oauth_signing_key_value(self) -> str:
        value = self.oauth_signing_key
        if isinstance(value, SecretStr):
            configured = value.get_secret_value().strip()
        else:
            configured = str(value or "").strip()
        # A separate key is mandatory in production.  Development keeps a
        # deterministic fallback so local onboarding and tests remain simple.
        if configured:
            return configured
        return self.secret_key if self.is_development else ""

    @property
    def normalized_oauth_issuer(self) -> str:
        value = (self.oauth_issuer or self.oauth_public_base_url).strip().rstrip("/")
        return value

    @property
    def normalized_oauth_public_base_url(self) -> str:
        value = (self.oauth_public_base_url or self.oauth_issuer).strip().rstrip("/")
        return value

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


settings = Settings()
