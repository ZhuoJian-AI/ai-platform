import pytest
from fastapi import HTTPException

from app.api.retirement import retired_api_dependency


@pytest.fixture(autouse=True)
def db_engine():
    """Compatibility-response unit tests do not require PostgreSQL."""
    yield


@pytest.mark.asyncio
async def test_retired_feature_returns_stable_chinese_410_shape():
    dependency = retired_api_dependency("旧功能")

    with pytest.raises(HTTPException) as error:
        await dependency.dependency()

    assert error.value.status_code == 410
    assert error.value.detail == {
        "code": "feature_retired",
        "message": "旧功能已下线；请使用统一 AI Assistant Core。",
        "retryable": False,
    }
