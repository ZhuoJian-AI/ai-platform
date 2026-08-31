"""Minimal, tenant-safe Coolify API client for native module releases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


class CoolifyModuleError(RuntimeError):
    def __init__(self, stage: str, detail: str):
        super().__init__(detail)
        self.stage = stage
        self.detail = detail


@dataclass(frozen=True)
class CoolifyTarget:
    server_uuid: str
    project_uuid: str
    environment_name: str
    environment_uuid: str | None
    destination_uuid: str | None
    github_app_uuid: str
    use_build_server: bool


def _base_url() -> str:
    value = settings.coolify_api_url.rstrip("/")
    return value if value.endswith("/api/v1") else f"{value}/api/v1"


def _message(payload: object, fallback: str) -> str:
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("detail") or fallback)[:1000]
    return fallback[:1000]


def redact_logs(value: str, secrets: tuple[str, ...] = ()) -> str:
    cleaned = value[-8000:]
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    cleaned = re.sub(
        r"(?i)(token|secret|password|authorization)(\s*[=:]\s*)[^\s,;]+",
        r"\1\2[REDACTED]",
        cleaned,
    )
    return cleaned


def classify_failure(logs: str, fallback: str = "Coolify deployment failed") -> tuple[str, str, str]:
    value = logs.lower()
    if any(
        item in value
        for item in (
            "git clone",
            "repository not found",
            "permission denied (publickey)",
            "authentication failed",
        )
    ):
        return "source", fallback, "检查 Coolify GitHub App 是否已安装到灼见组织并可读取该私有仓库。"
    if any(item in value for item in ("dockerfile", "failed to solve", "npm err", "pip install", "build failed")):
        return "build", fallback, "修复仓库中的 Dockerfile 或依赖后重新运行发布命令；旧版本仍保留。"
    if any(item in value for item in ("health check", "unhealthy", "connection refused", "port 8000")):
        return "health", fallback, "确认容器监听 0.0.0.0:8000，且 GET /health 返回 200。"
    if any(item in value for item in ("certificate", "let's encrypt", "traefik", "domain", "dns")):
        return "routing", fallback, "检查通配 DNS 是否指向目标 ECS，并确认 80/443 可达。"
    return "deploy", fallback, "查看日志摘要，修复后重试；平台不会删除应用或持久卷。"


class CoolifyModuleClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.coolify_module_deployer_configured:
            raise CoolifyModuleError("configuration", "Coolify module deployer is not configured")
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_base_url(),
            headers={
                "authorization": f"Bearer {settings.coolify_api_token}",
                "accept": "application/json",
                "user-agent": "ZhuoJian-Module-Deployer/1.0",
            },
            timeout=httpx.Timeout(settings.coolify_timeout_seconds, connect=10.0),
            transport=self._transport,
        )

    async def _request(self, method: str, path: str, *, stage: str, **kwargs) -> Any:
        try:
            async with self._client() as client:
                response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CoolifyModuleError(stage, f"Coolify is unavailable: {exc}") from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            raise CoolifyModuleError(
                stage,
                _message(payload, f"Coolify returned HTTP {response.status_code}"),
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise CoolifyModuleError(stage, "Coolify returned invalid JSON") from exc

    async def create_application(
        self,
        *,
        target: CoolifyTarget,
        repository: str,
        name: str,
        domain: str,
        commit: str,
    ) -> str:
        body: dict[str, Any] = {
            "project_uuid": target.project_uuid,
            "server_uuid": target.server_uuid,
            "environment_name": target.environment_name,
            "github_app_uuid": target.github_app_uuid,
            "git_repository": repository,
            "git_branch": "main",
            "git_commit_sha": commit,
            "ports_exposes": "8000",
            "build_pack": "dockerfile",
            "dockerfile_location": "/Dockerfile",
            "name": name,
            "description": "灼见原生企业子模块（由平台受控发布）",
            "domains": domain,
            "is_auto_deploy_enabled": False,
            "is_force_https_enabled": True,
            # The required Dockerfile already carries a runtime-native
            # HEALTHCHECK.  Avoid overriding it with curl/wget commands that
            # may not exist in small production images.
            "health_check_enabled": False,
            "use_build_server": target.use_build_server,
            "autogenerate_domain": False,
            "instant_deploy": False,
        }
        if target.environment_uuid:
            body["environment_uuid"] = target.environment_uuid
        if target.destination_uuid:
            body["destination_uuid"] = target.destination_uuid
        payload = await self._request(
            "POST", "/applications/private-github-app", stage="provision", json=body
        )
        application_uuid = str(payload.get("uuid") or "") if isinstance(payload, dict) else ""
        if not application_uuid:
            raise CoolifyModuleError("provision", "Coolify did not return an application UUID")
        return application_uuid

    async def update_release(self, application_uuid: str, *, domain: str, commit: str) -> None:
        await self._request(
            "PATCH",
            f"/applications/{application_uuid}",
            stage="provision",
            json={
                "domains": domain,
                "git_commit_sha": commit,
                "is_auto_deploy_enabled": False,
                "is_force_https_enabled": True,
                "health_check_enabled": False,
            },
        )

    async def set_envs(self, application_uuid: str, values: dict[str, str]) -> None:
        payload = await self._request(
            "GET", f"/applications/{application_uuid}/envs", stage="configuration"
        )
        existing = (
            {str(item.get("key")) for item in payload if isinstance(item, dict)}
            if isinstance(payload, list)
            else set()
        )
        for key, value in values.items():
            method = "PATCH" if key in existing else "POST"
            await self._request(
                method,
                f"/applications/{application_uuid}/envs",
                stage="configuration",
                json={
                    "key": key,
                    "value": value,
                    "is_preview": False,
                    "is_literal": True,
                    "is_multiline": False,
                    "is_shown_once": True,
                },
            )

    async def ensure_storage(self, application_uuid: str, volume_name: str) -> None:
        payload = await self._request(
            "GET", f"/applications/{application_uuid}/storages", stage="configuration"
        )
        rows = payload.get("persistent_storages", []) if isinstance(payload, dict) else []
        if any(isinstance(item, dict) and item.get("mount_path") == "/data" for item in rows):
            return
        await self._request(
            "POST",
            f"/applications/{application_uuid}/storages",
            stage="configuration",
            json={"type": "persistent", "name": volume_name, "mount_path": "/data"},
        )

    async def deploy(self, application_uuid: str) -> str:
        payload = await self._request(
            "POST", "/deploy", stage="deploy", json={"uuid": application_uuid}
        )
        deployments = payload.get("deployments", []) if isinstance(payload, dict) else []
        deployment_uuid = str(deployments[0].get("deployment_uuid") or "") if deployments else ""
        if not deployment_uuid:
            raise CoolifyModuleError("deploy", "Coolify did not return a deployment UUID")
        return deployment_uuid

    async def deployment(self, deployment_uuid: str) -> dict:
        payload = await self._request(
            "GET", f"/deployments/{deployment_uuid}", stage="deploy"
        )
        return payload if isinstance(payload, dict) else {}

    async def application_logs(self, application_uuid: str) -> str:
        payload = await self._request(
            "GET", f"/applications/{application_uuid}/logs", stage="logs", params={"lines": 120}
        )
        if isinstance(payload, dict):
            return str(payload.get("logs") or payload.get("message") or "")
        return str(payload)
