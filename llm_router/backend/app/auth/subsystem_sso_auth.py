"""Authentication for a subsystem redeeming a one-time SaaS launch code."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationIntegration,
)
from app.services.subsystem_access_service import assert_application_available
from app.utils.crypto import hash_api_key

SSO_EXCHANGE_CREDENTIAL_PREFIX = "zjss_"
STORED_PREFIX_LENGTH = 20


def extract_sso_exchange_credential(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token.startswith(SSO_EXCHANGE_CREDENTIAL_PREFIX):
            return token
    raise HTTPException(status_code=401, detail="Invalid subsystem SSO credential")


async def authenticate_subsystem_sso_client(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EnterpriseApplicationIntegration:
    raw = extract_sso_exchange_credential(request)
    if len(raw) < 40 or len(raw) > 512:
        raise HTTPException(status_code=401, detail="Invalid subsystem SSO credential")
    integration = (
        await db.execute(
            select(EnterpriseApplicationIntegration).where(
                EnterpriseApplicationIntegration.sso_exchange_credential_prefix
                == raw[:STORED_PREFIX_LENGTH],
                EnterpriseApplicationIntegration.sso_exchange_credential_hash
                == hash_api_key(raw),
                EnterpriseApplicationIntegration.sync_enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise HTTPException(status_code=401, detail="Invalid subsystem SSO credential")
    application = await db.get(EnterpriseApplication, integration.application_id)
    try:
        if application is None:
            raise HTTPException(status_code=409, detail="Subsystem application is unavailable")
        await assert_application_available(db, application)
    except HTTPException as exc:
        raise HTTPException(status_code=401, detail="Invalid subsystem SSO credential") from exc
    return integration
