"""Mandatory, hierarchical admission control for every billable AI call.

Redis is the synchronous source of truth for admission because a PostgreSQL
``SELECT`` followed by ``UPDATE`` cannot safely protect multiple Backend
replicas from concurrent overspend.  One Lua invocation checks and reserves
all applicable organization/department/team/API-key counters atomically.

Token reservations use a deliberately conservative upper bound.  Successful
responses are settled to provider-reported usage.  A failed, interrupted, or
otherwise unmetered call keeps its reservation, so missing usage can never be
used to bypass a cap.

One credit is one admitted platform-level logical AI operation. Provider
retry/failover inside that operation reuses the admission; failures do not
refund it, preventing free probing and abuse.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import and_, case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.api_key import ApiKey
from app.models.budget import AiQuotaEvent
from app.models.department import Department
from app.models.organization import Organization
from app.models.team import Team

logger = structlog.get_logger()


class QuotaExceededError(RuntimeError):
    """One hierarchy counter cannot accept the requested reservation."""

    def __init__(self, dimension: str, scope_type: str, retry_after_seconds: int):
        self.dimension = dimension
        self.scope_type = scope_type
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"{dimension} quota exceeded at {scope_type} scope")


class QuotaBackendUnavailableError(RuntimeError):
    """The mandatory production Redis ledger cannot be reached."""


class QuotaConfigurationError(RuntimeError):
    """A configured limit cannot be enforced truthfully."""


@dataclass(frozen=True)
class QuotaScope:
    scope_type: str
    scope_id: str
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_tokens: int | None = None
    budget_cap_credits: int | None = None
    budget_cap_usd: str | None = None
    baseline_rpm: int = 0
    baseline_tpm: int = 0
    baseline_budget_tokens: int = 0
    baseline_budget_credits: int = 0

    @property
    def has_token_limit(self) -> bool:
        return self.rate_limit_tpm is not None or self.budget_cap_tokens is not None

    @property
    def has_enforceable_limit(self) -> bool:
        return (
            self.rate_limit_rpm is not None
            or self.rate_limit_tpm is not None
            or self.budget_cap_tokens is not None
            or self.budget_cap_credits is not None
        )


@dataclass(frozen=True)
class QuotaReservation:
    reservation_id: str
    reserved_tokens: int
    counter_keys: tuple[str, ...] = ()
    enforced: bool = True
    reserved_credits: int = 1
    organization_id: str | None = None
    department_id: str | None = None
    team_id: str | None = None
    api_key_id: str | None = None
    provider_id: str | None = None
    operation: str | None = None
    scope_refs: tuple[tuple[str, str], ...] = ()
    admission_at: datetime | None = None
    rollback_entries: tuple[tuple[str, int], ...] = ()
    rollback_token: str | None = None

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        # Rollback is an admission-local capability. It must not survive into
        # graph checkpoints or other serialized request state.
        state.pop("rollback_entries", None)
        state.pop("rollback_token", None)
        state["counter_keys"] = list(self.counter_keys)
        state["scope_refs"] = [list(item) for item in self.scope_refs]
        state["admission_at"] = (
            self.admission_at.astimezone(UTC).isoformat()
            if self.admission_at is not None
            else None
        )
        return state

    @classmethod
    def from_state(cls, state: dict[str, Any] | None) -> QuotaReservation | None:
        if not state:
            return None
        return cls(
            reservation_id=str(state.get("reservation_id") or ""),
            reserved_tokens=max(0, int(state.get("reserved_tokens") or 0)),
            reserved_credits=max(0, int(state.get("reserved_credits") or 0)),
            counter_keys=tuple(str(key) for key in state.get("counter_keys") or []),
            enforced=bool(state.get("enforced", True)),
            organization_id=_optional_string(state.get("organization_id")),
            department_id=_optional_string(state.get("department_id")),
            team_id=_optional_string(state.get("team_id")),
            api_key_id=_optional_string(state.get("api_key_id")),
            provider_id=_optional_string(state.get("provider_id")),
            operation=_optional_string(state.get("operation")),
            scope_refs=tuple(
                (str(item[0]), str(item[1]))
                for item in state.get("scope_refs") or []
                if isinstance(item, (list, tuple)) and len(item) == 2
            ),
            admission_at=_parse_admission_at(state.get("admission_at")),
        )


_RESERVE_SCRIPT = r"""
local reservation_key = KEYS[1]
local scope_count = tonumber(ARGV[1])
local reserved_tokens = tonumber(ARGV[2])
local reserved_credits = tonumber(ARGV[3])
local minute_ttl = tonumber(ARGV[4])
local budget_ttl = tonumber(ARGV[5])
local reservation_ttl = tonumber(ARGV[6])
local rollback_token = ARGV[7 + (scope_count * 8)]

-- A transport retry with the same request id must not consume quota twice.
local existing_status = redis.call('HGET', reservation_key, 'status')
if existing_status and existing_status ~= 'aborted' then
  return {1, 'idempotent', 0}
end

for i = 1, scope_count do
  local key_offset = 2 + ((i - 1) * 4)
  local arg_offset = 7 + ((i - 1) * 8)
  local rpm_cap = tonumber(ARGV[arg_offset])
  local tpm_cap = tonumber(ARGV[arg_offset + 1])
  local token_cap = tonumber(ARGV[arg_offset + 2])
  local credit_cap = tonumber(ARGV[arg_offset + 3])
  local baseline_rpm = tonumber(ARGV[arg_offset + 4])
  local baseline_tpm = tonumber(ARGV[arg_offset + 5])
  local baseline_tokens = tonumber(ARGV[arg_offset + 6])
  local baseline_credits = tonumber(ARGV[arg_offset + 7])

  if rpm_cap >= 0 and redis.call('EXISTS', KEYS[key_offset]) == 0 then
    redis.call('SET', KEYS[key_offset], baseline_rpm, 'EX', minute_ttl)
  end
  if tpm_cap >= 0 and redis.call('EXISTS', KEYS[key_offset + 1]) == 0 then
    redis.call('SET', KEYS[key_offset + 1], baseline_tpm, 'EX', minute_ttl)
  end
  if token_cap >= 0 and redis.call('EXISTS', KEYS[key_offset + 2]) == 0 then
    redis.call('SET', KEYS[key_offset + 2], baseline_tokens, 'EX', budget_ttl)
  end
  if credit_cap >= 0 and redis.call('EXISTS', KEYS[key_offset + 3]) == 0 then
    redis.call('SET', KEYS[key_offset + 3], baseline_credits, 'EX', budget_ttl)
  end

  if rpm_cap >= 0 and tonumber(redis.call('GET', KEYS[key_offset]) or '0') + 1 > rpm_cap then
    return {0, 'rpm', i}
  end
  if tpm_cap >= 0 and tonumber(redis.call('GET', KEYS[key_offset + 1]) or '0') + reserved_tokens > tpm_cap then
    return {0, 'tpm', i}
  end
  if token_cap >= 0 and tonumber(redis.call('GET', KEYS[key_offset + 2]) or '0') + reserved_tokens > token_cap then
    return {0, 'token_budget', i}
  end
  if credit_cap >= 0 and tonumber(redis.call('GET', KEYS[key_offset + 3]) or '0') + reserved_credits > credit_cap then
    return {0, 'credit_budget', i}
  end
end

for i = 1, scope_count do
  local key_offset = 2 + ((i - 1) * 4)
  local arg_offset = 7 + ((i - 1) * 8)
  local rpm_cap = tonumber(ARGV[arg_offset])
  local tpm_cap = tonumber(ARGV[arg_offset + 1])
  local token_cap = tonumber(ARGV[arg_offset + 2])
  local credit_cap = tonumber(ARGV[arg_offset + 3])
  if rpm_cap >= 0 then redis.call('INCRBY', KEYS[key_offset], 1) end
  if tpm_cap >= 0 then redis.call('INCRBY', KEYS[key_offset + 1], reserved_tokens) end
  if token_cap >= 0 then redis.call('INCRBY', KEYS[key_offset + 2], reserved_tokens) end
  if credit_cap >= 0 then redis.call('INCRBY', KEYS[key_offset + 3], reserved_credits) end
end

redis.call('HSET', reservation_key,
  'status', 'open',
  'reserved_tokens', reserved_tokens,
  'reserved_credits', reserved_credits,
  'rollback_token', rollback_token,
  'counter_count', #KEYS - 1)
redis.call('EXPIRE', reservation_key, reservation_ttl)
return {1, 'reserved', 0}
"""


_SETTLE_SCRIPT = r"""
local reservation_key = KEYS[1]
if redis.call('HGET', reservation_key, 'status') ~= 'open' then return 0 end
local delta = tonumber(ARGV[1])
local actual_tokens = tonumber(ARGV[2])
for i = 2, #KEYS do
  if redis.call('EXISTS', KEYS[i]) == 1 and delta ~= 0 then
    local value = redis.call('INCRBY', KEYS[i], delta)
    if tonumber(value) < 0 then redis.call('SET', KEYS[i], 0) end
  end
end
redis.call('HSET', reservation_key, 'status', 'settled', 'actual_tokens', actual_tokens)
return 1
"""


_ABORT_SCRIPT = r"""
local reservation_key = KEYS[1]
local rollback_token = ARGV[1]
if redis.call('HGET', reservation_key, 'status') ~= 'open' then return 0 end
if redis.call('HGET', reservation_key, 'rollback_token') ~= rollback_token then return 0 end
for i = 2, #KEYS do
  local delta = tonumber(ARGV[i])
  if delta > 0 and redis.call('EXISTS', KEYS[i]) == 1 then
    local value = redis.call('INCRBY', KEYS[i], -delta)
    if tonumber(value) < 0 then redis.call('SET', KEYS[i], 0) end
  end
end
redis.call('HSET', reservation_key, 'status', 'aborted')
return 1
"""


class RedisQuotaEnforcer:
    """Thin Redis/Lua boundary; injectable so atomic behavior is testable."""

    _PREFIX = "ai-platform:ai-quota"

    def __init__(self, redis: Any | None = None) -> None:
        self.redis = redis or Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.ai_quota_redis_timeout_seconds,
            socket_timeout=settings.ai_quota_redis_timeout_seconds,
        )

    @staticmethod
    def _windows(now: datetime) -> tuple[str, str, int, int]:
        now = _normalize_admission_at(now)
        minute = now.strftime("%Y%m%d%H%M")
        month = now.strftime("%Y%m")
        minute_ttl = max(1, 120 - now.second)
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
        else:
            next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
        budget_ttl = max(1, int((next_month - now).total_seconds()) + 86400)
        return minute, month, minute_ttl, budget_ttl

    async def missing_counter_scopes(
        self,
        scopes: list[QuotaScope],
        *,
        now: datetime,
    ) -> set[tuple[str, str]]:
        """Batch-detect scopes whose Redis counters still need a PG baseline."""

        active = [scope for scope in scopes if scope.has_enforceable_limit]
        if not active:
            return set()
        organization = next(
            (scope for scope in scopes if scope.scope_type == "organization"),
            None,
        )
        if organization is None:
            raise QuotaConfigurationError("organization quota scope is required")
        minute, month, _minute_ttl, _budget_ttl = self._windows(now)
        prefix = f"{self._PREFIX}:{{{organization.scope_id}}}"
        keys: list[str] = []
        owners: list[tuple[str, str]] = []
        for scope in active:
            scope_prefix = f"{prefix}:{scope.scope_type}:{scope.scope_id}"
            dimensions = (
                (scope.rate_limit_rpm, f"{scope_prefix}:rpm:{minute}"),
                (scope.rate_limit_tpm, f"{scope_prefix}:tpm:{minute}"),
                (scope.budget_cap_tokens, f"{scope_prefix}:tokens:{month}"),
                (scope.budget_cap_credits, f"{scope_prefix}:credits:{month}"),
            )
            for cap, key in dimensions:
                if cap is not None:
                    keys.append(key)
                    owners.append((scope.scope_type, scope.scope_id))
        if not keys:
            return set()
        values = await self.redis.mget(*keys)
        if not isinstance(values, (list, tuple)) or len(values) != len(keys):
            raise QuotaBackendUnavailableError(
                "AI quota Redis returned invalid counter metadata"
            )
        return {
            owner
            for owner, value in zip(owners, values, strict=True)
            if value is None
        }

    async def reserve(
        self,
        scopes: list[QuotaScope],
        reserved_tokens: int,
        *,
        reserved_credits: int = 1,
        reservation_id: str,
        now: datetime,
    ) -> QuotaReservation:
        active = [scope for scope in scopes if scope.has_enforceable_limit]
        if not active:
            return QuotaReservation(
                reservation_id,
                reserved_tokens,
                reserved_credits=reserved_credits,
                enforced=False,
                admission_at=now,
            )
        organization = next((scope for scope in scopes if scope.scope_type == "organization"), None)
        if organization is None:
            raise QuotaConfigurationError("organization quota scope is required")
        minute, month, minute_ttl, budget_ttl = self._windows(now)
        # A shared hash tag keeps every key in one Redis Cluster slot, preserving
        # the atomic multi-scope Lua operation if deployment later uses Cluster.
        prefix = f"{self._PREFIX}:{{{organization.scope_id}}}"
        reservation_key = f"{prefix}:reservation:{reservation_id}"
        keys: list[str] = [reservation_key]
        settle_keys: list[str] = []
        rollback_entries: list[tuple[str, int]] = []
        rollback_token = uuid4().hex
        arguments: list[int | str] = [
            len(active),
            reserved_tokens,
            reserved_credits,
            minute_ttl,
            budget_ttl,
            max(budget_ttl, settings.ai_quota_reservation_ttl_seconds),
        ]
        for scope in active:
            scope_prefix = f"{prefix}:{scope.scope_type}:{scope.scope_id}"
            rpm_key = f"{scope_prefix}:rpm:{minute}"
            tpm_key = f"{scope_prefix}:tpm:{minute}"
            budget_key = f"{scope_prefix}:tokens:{month}"
            credit_key = f"{scope_prefix}:credits:{month}"
            keys.extend([rpm_key, tpm_key, budget_key, credit_key])
            arguments.extend(
                [
                    -1 if scope.rate_limit_rpm is None else scope.rate_limit_rpm,
                    -1 if scope.rate_limit_tpm is None else scope.rate_limit_tpm,
                    -1 if scope.budget_cap_tokens is None else scope.budget_cap_tokens,
                    -1 if scope.budget_cap_credits is None else scope.budget_cap_credits,
                    scope.baseline_rpm,
                    scope.baseline_tpm,
                    scope.baseline_budget_tokens,
                    scope.baseline_budget_credits,
                ]
            )
            if scope.rate_limit_tpm is not None:
                settle_keys.append(tpm_key)
            if scope.budget_cap_tokens is not None:
                settle_keys.append(budget_key)
            if scope.rate_limit_rpm is not None:
                rollback_entries.append((rpm_key, 1))
            if scope.rate_limit_tpm is not None:
                rollback_entries.append((tpm_key, reserved_tokens))
            if scope.budget_cap_tokens is not None:
                rollback_entries.append((budget_key, reserved_tokens))
            if scope.budget_cap_credits is not None:
                rollback_entries.append((credit_key, reserved_credits))

        arguments.append(rollback_token)
        result = await self.redis.eval(_RESERVE_SCRIPT, len(keys), *keys, *arguments)
        accepted = int(result[0]) == 1
        if not accepted:
            dimension = _decode_redis(result[1])
            scope_index = int(result[2]) - 1
            scope_type = active[scope_index].scope_type if 0 <= scope_index < len(active) else "unknown"
            retry_after = (
                max(1, 60 - now.second)
                if dimension in {"rpm", "tpm"}
                else budget_ttl - 86400
            )
            raise QuotaExceededError(dimension, scope_type, retry_after)
        newly_reserved = _decode_redis(result[1]) == "reserved"
        return QuotaReservation(
            reservation_id=reservation_id,
            reserved_tokens=reserved_tokens,
            reserved_credits=reserved_credits,
            counter_keys=tuple(settle_keys),
            admission_at=now,
            rollback_entries=tuple(rollback_entries) if newly_reserved else (),
            rollback_token=rollback_token if newly_reserved else None,
        )

    async def verify_persistence(self) -> None:
        """Reject production startup unless Redis reports AOF persistence."""

        try:
            info = await self.redis.info("persistence")
        except (RedisError, OSError, TimeoutError) as exc:
            raise QuotaBackendUnavailableError(
                "AI quota Redis persistence cannot be verified"
            ) from exc
        try:
            aof_enabled = int(info.get("aof_enabled", 0))
        except (TypeError, ValueError, AttributeError) as exc:
            raise QuotaBackendUnavailableError(
                "AI quota Redis returned invalid persistence metadata"
            ) from exc
        if aof_enabled != 1:
            raise QuotaBackendUnavailableError(
                "AI quota Redis must enable AOF persistence in production"
            )

    async def settle(self, reservation: QuotaReservation, actual_tokens: int | None) -> None:
        if not reservation.enforced:
            return
        # Unknown provider usage deliberately retains the full reservation.
        actual = reservation.reserved_tokens if actual_tokens is None else max(0, actual_tokens)
        delta = actual - reservation.reserved_tokens
        organization_tag = _organization_tag_from_counter_keys(reservation.counter_keys)
        if not organization_tag:
            # RPM-only reservations still have a Redis marker. Reconstruct its
            # organization tag from the reservation id is impossible, so the
            # marker can safely expire; there are no token counters to adjust.
            return
        reservation_key = (
            f"{self._PREFIX}:{{{organization_tag}}}:reservation:{reservation.reservation_id}"
        )
        keys = [reservation_key, *reservation.counter_keys]
        await self.redis.eval(_SETTLE_SCRIPT, len(keys), *keys, delta, actual)

    async def abort(self, reservation: QuotaReservation) -> bool:
        """Undo only the counters added by this exact, still-open attempt."""

        if (
            not reservation.enforced
            or not reservation.rollback_token
            or not reservation.rollback_entries
        ):
            return False
        counter_keys = tuple(key for key, _delta in reservation.rollback_entries)
        organization_tag = _organization_tag_from_counter_keys(counter_keys)
        if not organization_tag:
            raise QuotaConfigurationError("AI quota rollback counters have no organization tag")
        expected_prefix = f"{self._PREFIX}:{{{organization_tag}}}:"
        if any(not key.startswith(expected_prefix) for key in counter_keys):
            raise QuotaConfigurationError("AI quota rollback counters cross organization slots")
        reservation_key = (
            f"{self._PREFIX}:{{{organization_tag}}}:reservation:{reservation.reservation_id}"
        )
        keys = [reservation_key, *counter_keys]
        deltas = [delta for _key, delta in reservation.rollback_entries]
        result = await self.redis.eval(
            _ABORT_SCRIPT,
            len(keys),
            *keys,
            reservation.rollback_token,
            *deltas,
        )
        return int(result) == 1


def _decode_redis(value: Any) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _normalize_admission_at(value: datetime | None = None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise QuotaConfigurationError("AI quota admission time must be timezone-aware")
    return instant.astimezone(UTC)


def _parse_admission_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_admission_at(value)
    try:
        return _normalize_admission_at(datetime.fromisoformat(str(value)))
    except ValueError as exc:
        raise QuotaConfigurationError("AI quota admission time is invalid") from exc


def _organization_tag_from_counter_keys(keys: tuple[str, ...]) -> str | None:
    if not keys:
        return None
    first = keys[0]
    start = first.find("{")
    end = first.find("}", start + 1)
    return first[start + 1 : end] if start >= 0 and end > start else None


def quota_scopes_for_resources(
    organization: Organization,
    department: Department | None = None,
    team: Team | None = None,
    api_key: ApiKey | None = None,
    *,
    department_ancestors: list[Department] | tuple[Department, ...] = (),
) -> list[QuotaScope]:
    """Preserve every hierarchy cap so shared parent limits stay enforceable."""

    resources: list[tuple[str, Any]] = [("organization", organization)]
    resources.extend(("department", ancestor) for ancestor in department_ancestors)
    if department is not None:
        resources.append(("department", department))
    if team is not None:
        resources.append(("team", team))
    if api_key is not None:
        resources.append(("api_key", api_key))
    scopes = [
        QuotaScope(
            scope_type=scope_type,
            scope_id=str(resource.id),
            rate_limit_rpm=resource.rate_limit_rpm,
            rate_limit_tpm=resource.rate_limit_tpm,
            budget_cap_tokens=resource.budget_cap_tokens,
            budget_cap_credits=getattr(resource, "budget_cap_credits", None),
            budget_cap_usd=(
                str(resource.budget_cap_usd)
                if resource.budget_cap_usd is not None
                else None
            ),
        )
        for scope_type, resource in resources
    ]
    for scope in scopes:
        for name, value in (
            ("rate_limit_rpm", scope.rate_limit_rpm),
            ("rate_limit_tpm", scope.rate_limit_tpm),
            ("budget_cap_tokens", scope.budget_cap_tokens),
            ("budget_cap_credits", scope.budget_cap_credits),
        ):
            if value is not None and value < 0:
                raise QuotaConfigurationError(
                    f"{name} cannot be negative at {scope.scope_type} scope"
                )
    return scopes


def estimate_token_upper_bound(payload: Any, max_output_tokens: int = 0) -> int:
    """Return a tokenizer-independent upper bound based on UTF-8 bytes."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return max(1, len(encoded) + max(0, int(max_output_tokens)))


def usage_total_tokens(usage: dict[str, Any] | None) -> int | None:
    """Normalize provider usage only when it is complete and trustworthy."""

    if not usage:
        return None
    total = usage.get("total_tokens")
    if total is not None:
        try:
            return max(0, int(total))
        except (TypeError, ValueError):
            return None
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    try:
        return max(0, int(input_tokens)) + max(0, int(output_tokens))
    except (TypeError, ValueError):
        return None


def ensure_output_bound(body: dict[str, Any], protocol: str) -> tuple[dict[str, Any], int]:
    """Inject an enforceable output ceiling when the caller omitted one."""

    bounded = dict(body)
    value = bounded.get("max_completion_tokens", bounded.get("max_tokens"))
    try:
        maximum = int(value) if value is not None else settings.ai_quota_default_max_output_tokens
    except (TypeError, ValueError) as exc:
        raise QuotaConfigurationError("max_tokens must be an integer") from exc
    if maximum < 0:
        raise QuotaConfigurationError("max_tokens must be non-negative")
    if value is None:
        # Both supported proxy protocols accept max_tokens. Anthropic requires
        # it; OpenAI-compatible providers use it as a hard generation ceiling.
        bounded["max_tokens"] = maximum
    return bounded, maximum


async def _usage_baseline(
    db: AsyncSession,
    scope: QuotaScope,
    now: datetime,
) -> QuotaScope:
    if scope.scope_type not in {"organization", "department", "team", "api_key"}:
        raise QuotaConfigurationError(f"unknown quota scope: {scope.scope_type}")

    minute_start = now.replace(second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    reserved = (
        select(
            AiQuotaEvent.reservation_id,
            AiQuotaEvent.reserved_tokens,
            AiQuotaEvent.reserved_credits,
            AiQuotaEvent.created_at,
        )
        .where(
            AiQuotaEvent.scope_type == scope.scope_type,
            AiQuotaEvent.scope_id == scope.scope_id,
            AiQuotaEvent.event_type == "reserved",
        )
        .subquery("quota_reserved")
    )
    settled = (
        select(
            AiQuotaEvent.reservation_id,
            AiQuotaEvent.actual_tokens,
            AiQuotaEvent.actual_input_tokens,
            AiQuotaEvent.actual_output_tokens,
        )
        .where(
            AiQuotaEvent.scope_type == scope.scope_type,
            AiQuotaEvent.scope_id == scope.scope_id,
            AiQuotaEvent.event_type == "settled",
        )
        .subquery("quota_settled")
    )
    actual_or_reserved = case(
        (settled.c.actual_tokens.is_not(None), settled.c.actual_tokens),
        (
            and_(
                settled.c.actual_input_tokens.is_not(None),
                settled.c.actual_output_tokens.is_not(None),
            ),
            settled.c.actual_input_tokens + settled.c.actual_output_tokens,
        ),
        else_=reserved.c.reserved_tokens,
    )

    async def totals_since(since: datetime) -> tuple[int, int, int]:
        row = (
            await db.execute(
                select(
                    func.count(reserved.c.reservation_id),
                    func.coalesce(func.sum(actual_or_reserved), 0),
                    func.coalesce(func.sum(reserved.c.reserved_credits), 0),
                )
                .select_from(
                    reserved.outerjoin(
                        settled,
                        settled.c.reservation_id == reserved.c.reservation_id,
                    )
                )
                .where(reserved.c.created_at >= since)
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)

    minute_count, minute_tokens, _ = await totals_since(minute_start)
    _, month_tokens, month_credits = await totals_since(month_start)
    return replace(
        scope,
        baseline_rpm=minute_count,
        baseline_tpm=minute_tokens,
        baseline_budget_tokens=month_tokens,
        baseline_budget_credits=month_credits,
    )


async def load_quota_scopes(
    db: AsyncSession,
    organization_id: str | UUID,
    *,
    department_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    api_key: ApiKey | None = None,
    now: datetime | None = None,
    hydrate_baselines: bool = True,
) -> list[QuotaScope]:
    organization = await db.get(Organization, UUID(str(organization_id)))
    if organization is None or organization.deleted_at is not None:
        raise QuotaConfigurationError("organization quota scope is unavailable")
    department = None
    department_ancestors: list[Department] = []
    team = None
    if team_id is not None:
        team = await db.get(Team, UUID(str(team_id)))
        if (
            team is None
            or team.deleted_at is not None
            or str(team.organization_id) != str(organization.id)
        ):
            raise QuotaConfigurationError("team quota scope does not belong to organization")
        if department_id is None:
            department_id = team.department_id
    if department_id is not None:
        current_id: str | UUID | None = department_id
        seen: set[str] = set()
        chain: list[Department] = []
        while current_id is not None:
            normalized_id = str(current_id)
            if normalized_id in seen:
                raise QuotaConfigurationError("department quota hierarchy contains a cycle")
            seen.add(normalized_id)
            current = await db.get(Department, UUID(normalized_id))
            if (
                current is None
                or current.deleted_at is not None
                or str(current.organization_id) != str(organization.id)
            ):
                raise QuotaConfigurationError(
                    "department quota scope does not belong to organization"
                )
            chain.append(current)
            current_id = current.parent_id
        department = chain[0]
        department_ancestors = list(reversed(chain[1:]))
    if team is not None and department is not None and str(team.department_id) != str(department.id):
        raise QuotaConfigurationError("team quota scope does not belong to department")
    if api_key is not None and str(api_key.organization_id) != str(organization.id):
        raise QuotaConfigurationError("API key quota scope does not belong to organization")

    scopes = quota_scopes_for_resources(
        organization,
        department,
        team,
        api_key,
        department_ancestors=department_ancestors,
    )
    instant = _normalize_admission_at(now)
    if not hydrate_baselines:
        return scopes
    return [await _usage_baseline(db, scope, instant) for scope in scopes]


quota_enforcer = RedisQuotaEnforcer()


async def _hydrate_missing_quota_baselines(
    db: AsyncSession,
    scopes: list[QuotaScope],
    instant: datetime,
) -> list[QuotaScope]:
    """Read the durable ledger only when a scope's Redis window is unseeded."""

    try:
        missing = await quota_enforcer.missing_counter_scopes(scopes, now=instant)
    except QuotaConfigurationError:
        raise
    except (RedisError, OSError, TimeoutError, QuotaBackendUnavailableError) as exc:
        if settings.is_development and settings.ai_quota_development_fail_open:
            # Redis admission may explicitly degrade in development, but PG
            # baselines remain useful for tests and make recovery conservative.
            logger.warning(
                "ai_quota_counter_probe_development_degraded",
                error=str(exc)[:200],
            )
            missing = {
                (scope.scope_type, scope.scope_id)
                for scope in scopes
                if scope.has_enforceable_limit
            }
        else:
            raise QuotaBackendUnavailableError(
                "AI quota Redis counters cannot be inspected"
            ) from exc
    if not missing:
        return scopes
    return [
        await _usage_baseline(db, scope, instant)
        if (scope.scope_type, scope.scope_id) in missing
        else scope
        for scope in scopes
    ]


async def _append_quota_event(
    db: AsyncSession,
    reservation: QuotaReservation,
    event_type: str,
    *,
    usage: dict[str, Any] | None = None,
    outcome: str | None = None,
) -> None:
    """Commit one immutable phase per applicable hierarchy scope.

    A dedicated transaction is intentional: a provider exception must not roll
    back the durable reservation fact together with the business request.
    """

    if not reservation.scope_refs or reservation.organization_id is None:
        return
    bind = db.bind
    if bind is None:
        raise QuotaBackendUnavailableError("AI quota ledger database is unavailable")
    actual_tokens = usage_total_tokens(usage) if event_type == "settled" else None
    actual_input: int | None = None
    actual_output: int | None = None
    if actual_tokens is not None and usage:
        input_value = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_value = usage.get("output_tokens", usage.get("completion_tokens"))
        try:
            if input_value is not None and output_value is not None:
                actual_input = max(0, int(input_value))
                actual_output = max(0, int(output_value))
        except (TypeError, ValueError):
            actual_input = None
            actual_output = None
    rows = [
        {
            "id": uuid4(),
            "reservation_id": reservation.reservation_id,
            "organization_id": reservation.organization_id,
            "department_id": reservation.department_id,
            "team_id": reservation.team_id,
            "api_key_id": reservation.api_key_id,
            "provider_id": reservation.provider_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "event_type": event_type,
            "operation": reservation.operation,
            "outcome": outcome,
            "reserved_tokens": reservation.reserved_tokens,
            "reserved_credits": reservation.reserved_credits,
            "actual_tokens": actual_tokens,
            "actual_input_tokens": actual_input,
            "actual_output_tokens": actual_output,
            "created_at": (
                reservation.admission_at
                if event_type == "reserved" and reservation.admission_at is not None
                else datetime.now(UTC)
            ),
        }
        for scope_type, scope_id in reservation.scope_refs
    ]
    factory = async_sessionmaker(bind=bind, expire_on_commit=False)
    async with factory() as ledger_db:
        statement = pg_insert(AiQuotaEvent).values(rows).on_conflict_do_nothing(
            constraint="uq_ai_quota_event_phase"
        )
        await ledger_db.execute(statement)
        await ledger_db.commit()


async def _record_reservation_event(
    db: AsyncSession,
    reservation: QuotaReservation,
) -> None:
    try:
        await _append_quota_event(db, reservation, "reserved", outcome="admitted")
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise QuotaBackendUnavailableError("AI quota durable ledger is unavailable") from exc


async def reserve_scopes(
    scopes: list[QuotaScope],
    reserved_tokens: int,
    *,
    reserved_credits: int = 1,
    reservation_id: str | None = None,
    now: datetime | None = None,
    enforcer: RedisQuotaEnforcer | None = None,
) -> QuotaReservation:
    """Apply production fail-closed/development-explicit-degrade policy."""

    instant = _normalize_admission_at(now)
    active = [scope for scope in scopes if scope.has_enforceable_limit]
    rid = reservation_id or uuid4().hex
    if not active:
        return QuotaReservation(
            rid,
            max(0, int(reserved_tokens)),
            enforced=False,
            reserved_credits=max(0, int(reserved_credits)),
            admission_at=instant,
        )
    selected = enforcer or quota_enforcer
    try:
        return await selected.reserve(
            scopes,
            max(0, int(reserved_tokens)),
            reserved_credits=max(0, int(reserved_credits)),
            reservation_id=rid,
            now=instant,
        )
    except QuotaExceededError:
        raise
    except (RedisError, OSError, TimeoutError) as exc:
        if settings.is_development and settings.ai_quota_development_fail_open:
            logger.warning("ai_quota_development_degraded", error=str(exc)[:200])
            return QuotaReservation(
                rid,
                reserved_tokens,
                enforced=False,
                reserved_credits=max(0, int(reserved_credits)),
                admission_at=instant,
            )
        raise QuotaBackendUnavailableError("AI quota ledger is unavailable") from exc


async def reserve_ai_quota(
    db: AsyncSession,
    organization_id: str | UUID,
    *,
    payload: Any,
    max_output_tokens: int = 0,
    input_token_upper_bound: int | None = None,
    department_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    api_key: ApiKey | None = None,
    request_id: str | None = None,
    supports_token_metering: bool = True,
    provider_id: str | UUID | None = None,
    operation: str | None = None,
    admission_at: datetime | None = None,
) -> QuotaReservation:
    instant = _normalize_admission_at(admission_at)
    scopes = await load_quota_scopes(
        db,
        organization_id,
        department_id=department_id,
        team_id=team_id,
        api_key=api_key,
        now=instant,
        hydrate_baselines=False,
    )
    # Non-token-metered capabilities (for example image generation) are still
    # governed by RPM and the modality-neutral credit budget.  Token caps are
    # intentionally not claimed as enforced for those calls.
    enforceable_scopes = (
        scopes
        if supports_token_metering
        else [
            replace(scope, rate_limit_tpm=None, budget_cap_tokens=None)
            for scope in scopes
        ]
    )
    enforceable_scopes = await _hydrate_missing_quota_baselines(
        db,
        enforceable_scopes,
        instant,
    )
    reserved = 0
    if supports_token_metering:
        reserved = (
            max(1, int(input_token_upper_bound) + max(0, int(max_output_tokens)))
            if input_token_upper_bound is not None
            else estimate_token_upper_bound(payload, max_output_tokens)
        )
    reservation = await reserve_scopes(
        enforceable_scopes,
        reserved,
        reserved_credits=1,
        reservation_id=request_id,
        now=instant,
    )
    reservation = replace(
        reservation,
        organization_id=str(organization_id),
        department_id=_optional_string(department_id),
        team_id=_optional_string(team_id),
        api_key_id=_optional_string(api_key.id) if api_key is not None else None,
        provider_id=_optional_string(provider_id),
        operation=operation,
        scope_refs=tuple((scope.scope_type, scope.scope_id) for scope in scopes),
        admission_at=instant,
    )
    try:
        await _record_reservation_event(db, reservation)
    except QuotaBackendUnavailableError as ledger_exc:
        try:
            await quota_enforcer.abort(reservation)
        except (RedisError, OSError, TimeoutError, QuotaConfigurationError) as rollback_exc:
            logger.error(
                "ai_quota_reservation_rollback_unavailable",
                reservation_id=reservation.reservation_id,
                error=str(rollback_exc)[:200],
            )
        if settings.is_development and settings.ai_quota_development_fail_open:
            logger.warning(
                "ai_quota_ledger_development_degraded",
                reservation_id=reservation.reservation_id,
                error=str(ledger_exc)[:200],
            )
            return replace(
                reservation,
                enforced=False,
                rollback_entries=(),
                rollback_token=None,
            )
        raise
    return reservation


async def settle_ai_quota(
    reservation: QuotaReservation | dict[str, Any] | None,
    usage: dict[str, Any] | None,
    *,
    db: AsyncSession | None = None,
    outcome: str = "completed",
) -> None:
    parsed = (
        QuotaReservation.from_state(reservation)
        if isinstance(reservation, dict)
        else reservation
    )
    if parsed is None:
        return
    actual = usage_total_tokens(usage)
    if db is not None:
        try:
            await _append_quota_event(
                db,
                parsed,
                "settled",
                usage=usage,
                outcome=outcome if actual is not None else f"{outcome}_usage_unknown",
            )
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            # Admission already wrote an immutable reservation event. Keeping
            # that maximum is safe and makes the missing settlement visible.
            logger.error(
                "ai_quota_durable_settlement_unavailable",
                reservation_id=parsed.reservation_id,
                error=str(exc)[:200],
            )
    if parsed.enforced:
        try:
            await quota_enforcer.settle(parsed, actual)
        except (RedisError, OSError, TimeoutError) as exc:
            # Admission already reserved the conservative maximum. Retaining that
            # reservation is fail-closed, so a settlement outage must not turn a
            # completed provider response into a second user-visible failure.
            logger.error(
                "ai_quota_settlement_unavailable",
                reservation_id=parsed.reservation_id,
                error=str(exc)[:200],
            )


async def quota_startup_preflight(db: AsyncSession) -> None:
    """Verify the production ledger and surface frozen legacy USD settings."""

    legacy_counts: dict[str, int] = {}
    for scope_type, model in (
        ("organization", Organization),
        ("department", Department),
        ("team", Team),
        ("api_key", ApiKey),
    ):
        legacy_counts[scope_type] = int(
            (
                await db.execute(
                    select(func.count()).select_from(model).where(
                        model.budget_cap_usd.is_not(None)
                    )
                )
            ).scalar_one()
        )
    if any(legacy_counts.values()):
        logger.warning(
            "legacy_usd_budgets_read_only_not_enforced",
            counts=legacy_counts,
            replacement="budget_cap_tokens or budget_cap_credits",
        )
    if not settings.is_development:
        await quota_enforcer.verify_persistence()


def monotonic_request_id(prefix: str) -> str:
    """Small helper for internal calls that do not already own a request id."""

    return f"{prefix}-{int(time.time() * 1000)}-{uuid4().hex}"
