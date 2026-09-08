"""Compatibility responses for product surfaces retired by Assistant Core."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.params import Depends as DependsParam


def retired_api_dependency(feature_name: str) -> DependsParam:
    """Return a route dependency that gives old clients one stable 410 shape."""

    async def reject_retired_feature() -> None:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "feature_retired",
                "message": f"{feature_name}已下线；请使用统一 AI Assistant Core。",
                "retryable": False,
            },
        )

    dependency: Callable[[], Coroutine[Any, Any, None]] = reject_retired_feature
    return Depends(dependency)
