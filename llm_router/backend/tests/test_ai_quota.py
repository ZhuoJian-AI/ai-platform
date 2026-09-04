"""Atomic AI quota admission and conservative settlement tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.api.budget import get_budget_usage
from app.config import settings
from app.models.api_key import ApiKey
from app.models.budget import AiQuotaEvent
from app.models.organization import Organization
from app.schemas.organization import OrganizationCreate
from app.services import ai_quota_service as quota
from app.services import model_gateway


class AtomicRedis:
    """Minimal locked Redis/Lua model for deterministic concurrency tests."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.hashes: dict[str, dict[str, str | int]] = {}
        self.lock = asyncio.Lock()

    async def eval(self, script, numkeys, *items):
        keys = [str(value) for value in items[:numkeys]]
        args = list(items[numkeys:])
        async with self.lock:
            if script == quota._RESERVE_SCRIPT:
                return self._reserve(keys, args)
            if script == quota._SETTLE_SCRIPT:
                return self._settle(keys, args)
            if script == quota._ABORT_SCRIPT:
                return self._abort(keys, args)
            raise AssertionError("unexpected script")

    async def mget(self, *keys):
        async with self.lock:
            return [self.values.get(str(key)) for key in keys]

    def _reserve(self, keys: list[str], args: list[object]) -> list[object]:
        reservation_key = keys[0]
        existing = self.hashes.get(reservation_key)
        if existing and existing.get("status") != "aborted":
            return [1, "idempotent", 0]
        count = int(args[0])
        reserved = int(args[1])
        credits = int(args[2])
        rollback_token = str(args[6 + count * 8])
        for index in range(count):
            key_offset = 1 + index * 4
            arg_offset = 6 + index * 8
            rpm_cap, tpm_cap, budget_cap, credit_cap = (
                int(value) for value in args[arg_offset : arg_offset + 4]
            )
            baselines = [int(value) for value in args[arg_offset + 4 : arg_offset + 8]]
            for position, cap in enumerate((rpm_cap, tpm_cap, budget_cap, credit_cap)):
                if cap >= 0:
                    self.values.setdefault(keys[key_offset + position], baselines[position])
            if rpm_cap >= 0 and self.values[keys[key_offset]] + 1 > rpm_cap:
                return [0, "rpm", index + 1]
            if tpm_cap >= 0 and self.values[keys[key_offset + 1]] + reserved > tpm_cap:
                return [0, "tpm", index + 1]
            if budget_cap >= 0 and self.values[keys[key_offset + 2]] + reserved > budget_cap:
                return [0, "token_budget", index + 1]
            if credit_cap >= 0 and self.values[keys[key_offset + 3]] + credits > credit_cap:
                return [0, "credit_budget", index + 1]
        for index in range(count):
            key_offset = 1 + index * 4
            arg_offset = 6 + index * 8
            rpm_cap, tpm_cap, budget_cap, credit_cap = (
                int(value) for value in args[arg_offset : arg_offset + 4]
            )
            if rpm_cap >= 0:
                self.values[keys[key_offset]] += 1
            if tpm_cap >= 0:
                self.values[keys[key_offset + 1]] += reserved
            if budget_cap >= 0:
                self.values[keys[key_offset + 2]] += reserved
            if credit_cap >= 0:
                self.values[keys[key_offset + 3]] += credits
        self.hashes[reservation_key] = {
            "status": "open",
            "reserved_tokens": reserved,
            "reserved_credits": credits,
            "rollback_token": rollback_token,
        }
        return [1, "reserved", 0]

    def _settle(self, keys: list[str], args: list[object]) -> int:
        record = self.hashes.get(keys[0])
        if not record or record.get("status") != "open":
            return 0
        delta = int(args[0])
        for key in keys[1:]:
            if key in self.values:
                self.values[key] = max(0, self.values[key] + delta)
        record["status"] = "settled"
        record["actual_tokens"] = int(args[1])
        return 1

    def _abort(self, keys: list[str], args: list[object]) -> int:
        record = self.hashes.get(keys[0])
        if (
            not record
            or record.get("status") != "open"
            or record.get("rollback_token") != str(args[0])
        ):
            return 0
        for key, delta in zip(keys[1:], args[1:], strict=True):
            if key in self.values:
                self.values[key] = max(0, self.values[key] - int(delta))
        record["status"] = "aborted"
        return 1


class BrokenRedis:
    async def eval(self, *_args):
        raise ConnectionError("redis unavailable")


class PersistenceRedis:
    def __init__(self, enabled: int) -> None:
        self.enabled = enabled

    async def info(self, section: str):
        assert section == "persistence"
        return {"aof_enabled": self.enabled}


NOW = datetime(2026, 9, 4, 8, 30, 10, tzinfo=UTC)


def _enforcer(redis=None) -> quota.RedisQuotaEnforcer:
    return quota.RedisQuotaEnforcer(redis or AtomicRedis())


@pytest.mark.asyncio
async def test_concurrent_rpm_reservations_never_exceed_cap():
    enforcer = _enforcer()
    scopes = [quota.QuotaScope("organization", str(uuid4()), rate_limit_rpm=5)]

    async def attempt(index: int) -> bool:
        try:
            await quota.reserve_scopes(
                scopes,
                1,
                reservation_id=f"request-{index}",
                now=NOW,
                enforcer=enforcer,
            )
            return True
        except quota.QuotaExceededError:
            return False

    accepted = await asyncio.gather(*(attempt(index) for index in range(40)))
    assert sum(accepted) == 5


@pytest.mark.asyncio
async def test_zero_quota_is_an_explicit_denial():
    scopes = [quota.QuotaScope("organization", str(uuid4()), budget_cap_tokens=0)]
    with pytest.raises(quota.QuotaExceededError) as caught:
        await quota.reserve_scopes(scopes, 1, now=NOW, enforcer=_enforcer())
    assert caught.value.dimension == "token_budget"
    assert caught.value.scope_type == "organization"


@pytest.mark.asyncio
async def test_every_hierarchy_counter_is_checked_and_api_key_is_most_restrictive():
    org_id, dept_id, team_id, key_id = (str(uuid4()) for _ in range(4))
    scopes = [
        quota.QuotaScope("organization", org_id, rate_limit_rpm=100),
        quota.QuotaScope("department", dept_id, rate_limit_rpm=50),
        quota.QuotaScope("team", team_id, rate_limit_rpm=30),
        quota.QuotaScope("api_key", key_id, rate_limit_rpm=1),
    ]
    enforcer = _enforcer()
    await quota.reserve_scopes(scopes, 1, reservation_id="first", now=NOW, enforcer=enforcer)
    with pytest.raises(quota.QuotaExceededError) as caught:
        await quota.reserve_scopes(scopes, 1, reservation_id="second", now=NOW, enforcer=enforcer)
    assert caught.value.scope_type == "api_key"
    assert caught.value.dimension == "rpm"


@pytest.mark.asyncio
async def test_success_refunds_to_real_usage_but_failure_keeps_reservation():
    org_id = str(uuid4())
    scopes = [quota.QuotaScope("organization", org_id, budget_cap_tokens=100)]
    enforcer = _enforcer()
    first = await quota.reserve_scopes(
        scopes,
        80,
        reservation_id="success",
        now=NOW,
        enforcer=enforcer,
    )
    await enforcer.settle(first, 20)
    # 20 actual + 80 reserved reaches the cap exactly.
    await quota.reserve_scopes(
        scopes,
        80,
        reservation_id="after-refund",
        now=NOW,
        enforcer=enforcer,
    )

    failed_org = str(uuid4())
    failed_scopes = [quota.QuotaScope("organization", failed_org, budget_cap_tokens=100)]
    failed = await quota.reserve_scopes(
        failed_scopes,
        80,
        reservation_id="failed",
        now=NOW,
        enforcer=enforcer,
    )
    await enforcer.settle(failed, None)
    with pytest.raises(quota.QuotaExceededError):
        await quota.reserve_scopes(
            failed_scopes,
            21,
            reservation_id="failure-retains-maximum",
            now=NOW,
            enforcer=enforcer,
        )


@pytest.mark.asyncio
async def test_settlement_is_idempotent():
    redis = AtomicRedis()
    enforcer = _enforcer(redis)
    scope = quota.QuotaScope("organization", str(uuid4()), budget_cap_tokens=100)
    reservation = await quota.reserve_scopes(
        [scope],
        80,
        reservation_id="idempotent",
        now=NOW,
        enforcer=enforcer,
    )
    await enforcer.settle(reservation, 20)
    await enforcer.settle(reservation, 0)
    budget_values = [value for key, value in redis.values.items() if ":tokens:" in key]
    assert budget_values == [20]


@pytest.mark.asyncio
async def test_durable_reservation_failure_rolls_back_only_its_attempt(monkeypatch):
    org_id = str(uuid4())
    department_id = str(uuid4())
    scopes = [
        quota.QuotaScope(
            "organization",
            org_id,
            rate_limit_rpm=100,
            rate_limit_tpm=1_000,
            budget_cap_tokens=10_000,
            budget_cap_credits=100,
        ),
        quota.QuotaScope(
            "department",
            department_id,
            rate_limit_rpm=100,
            rate_limit_tpm=1_000,
            budget_cap_tokens=10_000,
            budget_cap_credits=100,
        ),
    ]
    redis = AtomicRedis()
    enforcer = _enforcer(redis)
    monkeypatch.setattr(quota, "quota_enforcer", enforcer)
    monkeypatch.setattr(settings, "app_env", "production")

    async def load_scopes(*_args, **_kwargs):
        return scopes

    failed_reservations: list[quota.QuotaReservation] = []

    async def fail_durable_write(_db, reservation):
        failed_reservations.append(reservation)
        raise quota.QuotaBackendUnavailableError("ledger unavailable")

    monkeypatch.setattr(quota, "load_quota_scopes", load_scopes)
    monkeypatch.setattr(quota, "_record_reservation_event", fail_durable_write)

    await quota.reserve_scopes(
        scopes,
        3,
        reserved_credits=1,
        reservation_id="other-request",
        now=NOW,
        enforcer=enforcer,
    )
    before = dict(redis.values)

    with pytest.raises(quota.QuotaBackendUnavailableError, match="ledger unavailable"):
        await quota.reserve_ai_quota(
            object(),
            org_id,
            department_id=department_id,
            payload={"messages": [{"role": "user", "content": "hello"}]},
            input_token_upper_bound=4,
            max_output_tokens=3,
            request_id="failed-ledger-write",
            admission_at=NOW,
        )

    assert redis.values == before
    failed = failed_reservations[0]
    assert await enforcer.abort(failed) is False
    assert redis.values == before

    retried = await quota.reserve_scopes(
        scopes,
        7,
        reserved_credits=1,
        reservation_id="failed-ledger-write",
        now=NOW,
        enforcer=enforcer,
    )
    after_retry = dict(redis.values)
    assert retried.rollback_token != failed.rollback_token
    assert await enforcer.abort(failed) is False
    assert redis.values == after_retry
    assert all(
        after_retry[key] - before[key] == (1 if ":rpm:" in key or ":credits:" in key else 7)
        for key in before
    )


@pytest.mark.asyncio
async def test_production_redis_failure_is_closed_and_development_is_explicit(monkeypatch):
    scopes = [quota.QuotaScope("organization", str(uuid4()), rate_limit_rpm=10)]
    broken = _enforcer(BrokenRedis())
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(quota.QuotaBackendUnavailableError):
        await quota.reserve_scopes(scopes, 1, now=NOW, enforcer=broken)

    monkeypatch.setattr(settings, "app_env", "development")
    degraded = await quota.reserve_scopes(scopes, 1, now=NOW, enforcer=broken)
    assert degraded.enforced is False


@pytest.mark.asyncio
async def test_production_persistence_preflight_requires_aof():
    await _enforcer(PersistenceRedis(1)).verify_persistence()
    with pytest.raises(quota.QuotaBackendUnavailableError, match="AOF"):
        await _enforcer(PersistenceRedis(0)).verify_persistence()


@pytest.mark.asyncio
async def test_legacy_usd_cap_does_not_block_existing_tenant():
    scopes = [
        quota.QuotaScope(
            "organization",
            str(uuid4()),
            budget_cap_usd="5.00",
        )
    ]
    reservation = await quota.reserve_scopes(scopes, 1, now=NOW, enforcer=_enforcer())
    assert reservation.enforced is False


def test_new_usd_budget_configuration_is_rejected():
    with pytest.raises(ValidationError):
        OrganizationCreate(
            name="No Fake Dollar Meter",
            slug="no-fake-dollar-meter",
            budget_cap_usd="5.00",
        )


@pytest.mark.asyncio
async def test_zero_credit_budget_blocks_unmetered_call():
    scopes = [quota.QuotaScope("organization", str(uuid4()), budget_cap_credits=0)]
    with pytest.raises(quota.QuotaExceededError) as caught:
        await quota.reserve_scopes(
            scopes,
            0,
            reserved_credits=1,
            now=NOW,
            enforcer=_enforcer(),
        )
    assert caught.value.dimension == "credit_budget"


@pytest.mark.asyncio
async def test_credit_is_not_refunded_after_success_or_failure():
    scope = quota.QuotaScope(
        "organization",
        str(uuid4()),
        budget_cap_tokens=100,
        budget_cap_credits=1,
    )
    enforcer = _enforcer()
    admitted = await quota.reserve_scopes(
        [scope],
        80,
        reservation_id="credit-success",
        now=NOW,
        enforcer=enforcer,
    )
    await enforcer.settle(admitted, 1)
    with pytest.raises(quota.QuotaExceededError) as caught:
        await quota.reserve_scopes(
            [scope],
            1,
            reservation_id="credit-still-spent",
            now=NOW,
            enforcer=enforcer,
        )
    assert caught.value.dimension == "credit_budget"


@pytest.mark.asyncio
async def test_reused_logical_operation_id_consumes_one_credit():
    redis = AtomicRedis()
    enforcer = _enforcer(redis)
    scope = quota.QuotaScope(
        "organization",
        str(uuid4()),
        rate_limit_rpm=1,
        budget_cap_credits=1,
    )

    await quota.reserve_scopes(
        [scope],
        0,
        reservation_id="one-audio-job",
        now=NOW,
        enforcer=enforcer,
    )
    await quota.reserve_scopes(
        [scope],
        0,
        reservation_id="one-audio-job",
        now=NOW,
        enforcer=enforcer,
    )

    credit_values = [value for key, value in redis.values.items() if ":credits:" in key]
    rpm_values = [value for key, value in redis.values.items() if ":rpm:" in key]
    assert credit_values == [1]
    assert rpm_values == [1]
    with pytest.raises(quota.QuotaExceededError):
        await quota.reserve_scopes(
            [scope],
            0,
            reservation_id="another-audio-job",
            now=NOW,
            enforcer=enforcer,
        )


@pytest.mark.asyncio
async def test_credit_hierarchy_uses_most_restrictive_scope():
    scopes = [
        quota.QuotaScope("organization", str(uuid4()), budget_cap_credits=10),
        quota.QuotaScope("department", str(uuid4()), budget_cap_credits=5),
        quota.QuotaScope("team", str(uuid4()), budget_cap_credits=2),
        quota.QuotaScope("api_key", str(uuid4()), budget_cap_credits=1),
    ]
    enforcer = _enforcer()
    await quota.reserve_scopes(scopes, 0, now=NOW, enforcer=enforcer)
    with pytest.raises(quota.QuotaExceededError) as caught:
        await quota.reserve_scopes(scopes, 0, now=NOW, enforcer=enforcer)
    assert caught.value.dimension == "credit_budget"
    assert caught.value.scope_type == "api_key"


@pytest.mark.asyncio
async def test_append_only_ledger_rebuilds_token_and_credit_baseline(
    db_session,
    monkeypatch,
):
    organization = Organization(
        name="Quota Ledger Org",
        slug=f"quota-ledger-{uuid4().hex[:8]}",
        settings={},
        budget_cap_tokens=10_000,
        budget_cap_credits=10,
    )
    db_session.add(organization)
    await db_session.flush()
    monkeypatch.setattr(quota, "quota_enforcer", _enforcer())

    reservation = await quota.reserve_ai_quota(
        db_session,
        organization.id,
        payload={"messages": [{"role": "user", "content": "hello"}]},
        max_output_tokens=100,
        request_id="durable-ledger-test",
        operation="chat",
    )
    await quota.settle_ai_quota(
        reservation,
        {"input_tokens": 3, "output_tokens": 2},
        db=db_session,
        outcome="completed",
    )

    events = list(
        (
            await db_session.execute(
                select(AiQuotaEvent)
                .where(AiQuotaEvent.reservation_id == "durable-ledger-test")
                .order_by(AiQuotaEvent.event_type)
            )
        ).scalars()
    )
    assert {event.event_type for event in events} == {"reserved", "settled"}
    assert all(event.reserved_credits == 1 for event in events)
    settled = next(event for event in events if event.event_type == "settled")
    assert settled.actual_tokens == 5
    assert settled.outcome == "completed"

    scopes = await quota.load_quota_scopes(db_session, organization.id, now=NOW)
    assert scopes[0].baseline_budget_tokens == 5
    assert scopes[0].baseline_budget_credits == 1


@pytest.mark.asyncio
async def test_unmetered_capability_consumes_credit_without_fake_tokens(
    db_session,
    monkeypatch,
):
    organization = Organization(
        name="Image Credit Org",
        slug=f"image-credit-{uuid4().hex[:8]}",
        settings={},
        budget_cap_tokens=0,
        budget_cap_credits=2,
    )
    db_session.add(organization)
    await db_session.flush()
    redis = AtomicRedis()
    monkeypatch.setattr(quota, "quota_enforcer", _enforcer(redis))

    reservation = await quota.reserve_ai_quota(
        db_session,
        organization.id,
        payload={"prompt": "a garment"},
        supports_token_metering=False,
        request_id="image-credit-test",
        operation="image-generation",
    )
    assert reservation.reserved_tokens == 0
    assert reservation.reserved_credits == 1
    assert not any(":tokens:" in key for key in redis.values)
    assert [value for key, value in redis.values.items() if ":credits:" in key] == [1]


@pytest.mark.asyncio
async def test_budget_report_keeps_revoked_key_history_from_ledger(
    db_session,
    monkeypatch,
):
    organization = Organization(
        name="Revoked Key History Org",
        slug=f"revoked-history-{uuid4().hex[:8]}",
        settings={},
        budget_cap_credits=10,
    )
    db_session.add(organization)
    await db_session.flush()
    api_key = ApiKey(
        key_prefix=f"sk-{uuid4().hex[:9]}",
        key_hash=uuid4().hex,
        key_encrypted="",
        key_name="historical-key",
        scope_type="organization",
        organization_id=organization.id,
        allowed_models=[],
        budget_cap_credits=5,
    )
    db_session.add(api_key)
    await db_session.flush()
    monkeypatch.setattr(quota, "quota_enforcer", _enforcer())

    reservation = await quota.reserve_ai_quota(
        db_session,
        organization.id,
        api_key=api_key,
        payload={"messages": [{"role": "user", "content": "hello"}]},
        max_output_tokens=50,
        request_id="revoked-key-ledger-test",
        operation="proxy-chat",
    )
    await quota.settle_ai_quota(
        reservation,
        {"input_tokens": 4, "output_tokens": 3},
        db=db_session,
    )
    api_key.revoked_at = datetime.now(UTC)
    api_key.is_active = False
    await db_session.flush()

    report = await get_budget_usage(
        organization.id,
        object(),
        db_session,
        start_date=NOW.date().replace(day=1),
        end_date=date(2026, 10, 1),
        include_revoked=False,
    )
    historical = next(item for item in report["api_keys"] if item["api_key_id"] == str(api_key.id))
    assert historical["is_revoked"] is True
    assert historical["total_tokens"] == 7
    assert historical["credits"] == 1
    assert historical["effective_remaining"] == {
        "monthly_tokens": None,
        "monthly_credits": 4,
    }
    assert report["timezone"] == "UTC"
    assert report["retained_unknown_tokens"] == 0
    organization_scope = next(
        item for item in report["scopes"] if item["scope_type"] == "organization"
    )
    key_scope = next(
        item
        for item in report["scopes"]
        if item["scope_type"] == "api_key" and item["scope_id"] == str(api_key.id)
    )
    assert organization_scope["usage"]["actual_tokens"] == 7
    assert organization_scope["effective_remaining"]["monthly_credits"] == 9
    assert key_scope["effective_remaining"]["monthly_credits"] == 4
    assert report["enforcement"]["durable_ledger"] == "postgresql_append_only"


def test_resource_scopes_preserve_parent_and_child_limits():
    org_id, dept_id, team_id, key_id = (uuid4() for _ in range(4))
    organization = SimpleNamespace(
        id=org_id,
        rate_limit_rpm=100,
        rate_limit_tpm=1000,
        budget_cap_tokens=10_000,
        budget_cap_usd=None,
    )
    department = SimpleNamespace(
        id=dept_id,
        rate_limit_rpm=50,
        rate_limit_tpm=None,
        budget_cap_tokens=None,
        budget_cap_usd=None,
    )
    team = SimpleNamespace(
        id=team_id,
        rate_limit_rpm=10,
        rate_limit_tpm=None,
        budget_cap_tokens=None,
        budget_cap_usd=None,
    )
    api_key = SimpleNamespace(
        id=key_id,
        rate_limit_rpm=3,
        rate_limit_tpm=None,
        budget_cap_tokens=500,
        budget_cap_usd=None,
    )
    scopes = quota.quota_scopes_for_resources(organization, department, team, api_key)
    assert [scope.scope_type for scope in scopes] == [
        "organization",
        "department",
        "team",
        "api_key",
    ]
    assert min(scope.rate_limit_rpm for scope in scopes if scope.rate_limit_rpm is not None) == 3
    assert scopes[-1].budget_cap_tokens == 500


def test_partial_usage_is_not_treated_as_complete():
    assert quota.usage_total_tokens({"input_tokens": 10, "output_tokens": None}) is None
    assert quota.usage_total_tokens({"input_tokens": 10, "output_tokens": 4}) == 14


@pytest.mark.asyncio
async def test_gateway_failure_keeps_reservation(monkeypatch):
    reservation = quota.QuotaReservation("gateway-failure", 100, ("counter",))
    settled: list[dict | None] = []

    async def fail():
        raise RuntimeError("upstream failed")

    async def record(_reservation, usage, **_kwargs):
        settled.append(usage)

    monkeypatch.setattr(model_gateway, "settle_ai_quota", record)
    with pytest.raises(RuntimeError, match="upstream failed"):
        await model_gateway._metered_result(object(), reservation, fail, lambda _result: {})
    assert settled == [None]


@pytest.mark.asyncio
async def test_stream_disconnect_keeps_conservative_reservation(monkeypatch):
    reservation = quota.QuotaReservation("stream-disconnect", 100, ("counter",))
    settled: list[dict | None] = []

    async def allow(*_args, **_kwargs):
        return reservation

    async def fake_stream(*_args, **_kwargs):
        yield ("text", "partial", None)
        yield ("usage", None, {"input_tokens": 5, "output_tokens": 2})

    async def record(_reservation, usage, **_kwargs):
        settled.append(usage)

    monkeypatch.setattr(model_gateway, "_reserve_gateway_quota", allow)
    monkeypatch.setattr(model_gateway, "_stream_chat_unmetered", fake_stream)
    monkeypatch.setattr(model_gateway, "settle_ai_quota", record)
    stream = model_gateway.stream_chat(
        object(),
        uuid4(),
        "test-model",
        [{"role": "user", "content": "hello"}],
    )
    assert await anext(stream) == ("text", "partial", None)
    await stream.aclose()
    assert settled == [None]
