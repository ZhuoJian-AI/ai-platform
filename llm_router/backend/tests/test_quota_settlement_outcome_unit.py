"""Regression for disconnected streams whose final token usage is unavailable."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.budget import AiQuotaEvent
from app.services import ai_quota_service as quota


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,usage,expected", [
    ("disconnected", None, "disconnect_usage_unknown"),
    ("completed", None, "completed_usage_unknown"),
    ("failed", None, "failed_usage_unknown"),
    ("disconnected", {"total_tokens": 7}, "disconnected"),
    ("completed", {"total_tokens": 7}, "completed"),
])
async def test_settlement_fits_existing_ledger_without_changing_usage(
    monkeypatch, outcome, usage, expected,
):
    append = AsyncMock()
    monkeypatch.setattr(quota, "_append_quota_event", append)
    reservation = SimpleNamespace(enforced=False)
    db = object()
    await quota.settle_ai_quota(reservation, usage, db=db, outcome=outcome)
    append.assert_awaited_once_with(db, reservation, "settled", usage=usage, outcome=expected)
    assert len(expected) <= AiQuotaEvent.__table__.c.outcome.type.length
