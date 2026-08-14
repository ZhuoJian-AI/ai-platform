"""Public runtime configuration endpoint.

暴露给前端的安全、非敏感配置项。当前仅返回代理对外 Base URL，
供「接入指引」展示——该值由部署方在 .env 中按实际部署与连通性测试结果配置。
"""

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/config")
async def get_public_config() -> dict:
    """返回前端需要的公共配置（无需鉴权）。"""
    return {
        "proxy_base_url": settings.normalized_proxy_base_url,
    }
