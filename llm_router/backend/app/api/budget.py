"""Durable AI quota usage grouped by API key and provider.

Usage comes from the append-only quota ledger rather than mutable API-key
metadata or request AuditLog rows. Revoking a key therefore never erases its
history, and failed/unmetered calls remain visible through credits and retained
reservations.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.admin_auth import CurrentAdmin, require_org_access
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.budget import AiQuotaEvent
from app.models.department import Department
from app.models.llm_provider import LlmProvider
from app.models.organization import Organization
from app.models.team import Team

router = APIRouter()


def _month_range(ref: date | None = None) -> tuple[date, date]:
    """Return the half-open calendar month containing ``ref``."""

    today = ref or datetime.now(UTC).date()
    period_start = today.replace(day=1)
    if today.month == 12:
        period_end = date(today.year + 1, 1, 1)
    else:
        period_end = date(today.year, today.month + 1, 1)
    return period_start, period_end


def _empty_key_bucket(
    *,
    api_key_id: str | None,
    key_name: str,
    key_prefix: str | None,
    token_cap: int | None,
    credit_cap: int | None,
    is_revoked: bool,
) -> dict:
    return {
        "api_key_id": api_key_id,
        "key_name": key_name,
        "key_prefix": key_prefix,
        "budget_cap_tokens": token_cap,
        "budget_cap_credits": credit_cap,
        "is_revoked": is_revoked,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "retained_unknown_tokens": 0,
        "credits": 0,
        "request_count": 0,
        "providers": [],
    }


def _scope_bucket(
    *,
    scope_type: str,
    scope_id: str,
    scope_name: str,
    parent_scope_type: str | None,
    parent_scope_id: str | None,
    rate_limit_rpm: int | None,
    rate_limit_tpm: int | None,
    token_cap: int | None,
    credit_cap: int | None,
    is_inactive: bool,
) -> dict:
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "scope_name": scope_name,
        "parent_scope_type": parent_scope_type,
        "parent_scope_id": parent_scope_id,
        "is_inactive": is_inactive,
        "direct_caps": {
            "rpm": rate_limit_rpm,
            "tpm": rate_limit_tpm,
            "monthly_tokens": token_cap,
            "monthly_credits": credit_cap,
        },
        "usage": {
            "actual_tokens": 0,
            "held_unknown_tokens": 0,
            "credits": 0,
            "requests": 0,
        },
    }


def _remaining(cap: int | None, used: int) -> int | None:
    return None if cap is None else max(0, int(cap) - used)


def _attach_scope_remaining(scopes: dict[tuple[str, str], dict]) -> None:
    """Attach direct and inherited remaining quota without double-counting siblings."""

    for bucket in scopes.values():
        usage = bucket["usage"]
        caps = bucket["direct_caps"]
        direct = {
            "monthly_tokens": _remaining(
                caps["monthly_tokens"],
                usage["actual_tokens"] + usage["held_unknown_tokens"],
            ),
            "monthly_credits": _remaining(caps["monthly_credits"], usage["credits"]),
        }
        bucket["direct_remaining"] = direct

    for key, bucket in scopes.items():
        chain: list[dict] = []
        seen: set[tuple[str, str]] = set()
        cursor: tuple[str, str] | None = key
        while cursor is not None:
            if cursor in seen:
                raise HTTPException(status_code=500, detail="Quota scope hierarchy contains a cycle")
            seen.add(cursor)
            current = scopes.get(cursor)
            if current is None:
                break
            chain.append(current)
            parent_type = current.get("parent_scope_type")
            parent_id = current.get("parent_scope_id")
            cursor = (parent_type, parent_id) if parent_type and parent_id else None
        bucket["effective_remaining"] = {
            field: min(values) if values else None
            for field in ("monthly_tokens", "monthly_credits")
            if (
                values := [
                    item["direct_remaining"][field]
                    for item in chain
                    if item["direct_remaining"][field] is not None
                ]
            )
        }
        for field in ("monthly_tokens", "monthly_credits"):
            bucket["effective_remaining"].setdefault(field, None)


@router.get("/organizations/{org_id}/budget/usage")
async def get_budget_usage(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
    start_date: date | None = Query(None, description="起始日期（含），默认当月 1 日"),
    end_date: date | None = Query(None, description="结束日期（不含），默认下月 1 日"),
    include_revoked: bool = Query(False, description="是否包含无用量的已撤销 API Key"),
) -> dict:
    """Return settled tokens, conservative holds, credits and call counts."""

    as_of = datetime.now(UTC)
    period_start, period_end = _month_range(as_of.date())
    period_start = start_date or period_start
    period_end = end_date or period_end
    if period_end <= period_start:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")
    org_id_str = str(org_id)

    organization = await db.get(Organization, org_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Organization not found")

    department_rows = (
        await db.execute(
            select(
                Department.id,
                Department.parent_id,
                Department.name,
                Department.rate_limit_rpm,
                Department.rate_limit_tpm,
                Department.budget_cap_tokens,
                Department.budget_cap_credits,
                Department.deleted_at,
            ).where(Department.organization_id == org_id_str)
        )
    ).all()
    team_rows = (
        await db.execute(
            select(
                Team.id,
                Team.department_id,
                Team.name,
                Team.rate_limit_rpm,
                Team.rate_limit_tpm,
                Team.budget_cap_tokens,
                Team.budget_cap_credits,
                Team.deleted_at,
            ).where(Team.organization_id == org_id_str)
        )
    ).all()

    key_rows = (
        await db.execute(
            select(
                ApiKey.id,
                ApiKey.key_name,
                ApiKey.key_prefix,
                ApiKey.budget_cap_tokens,
                ApiKey.budget_cap_credits,
                ApiKey.scope_type,
                ApiKey.department_id,
                ApiKey.team_id,
                ApiKey.rate_limit_rpm,
                ApiKey.rate_limit_tpm,
                ApiKey.revoked_at,
            ).where(ApiKey.organization_id == org_id_str)
        )
    ).all()
    keys_meta = {
        str(key.id): _empty_key_bucket(
            api_key_id=str(key.id),
            key_name=key.key_name,
            key_prefix=key.key_prefix,
            token_cap=key.budget_cap_tokens,
            credit_cap=key.budget_cap_credits,
            is_revoked=key.revoked_at is not None,
        )
        for key in key_rows
    }

    scopes: dict[tuple[str, str], dict] = {}
    scopes[("organization", org_id_str)] = _scope_bucket(
        scope_type="organization",
        scope_id=org_id_str,
        scope_name=organization.name,
        parent_scope_type=None,
        parent_scope_id=None,
        rate_limit_rpm=organization.rate_limit_rpm,
        rate_limit_tpm=organization.rate_limit_tpm,
        token_cap=organization.budget_cap_tokens,
        credit_cap=organization.budget_cap_credits,
        is_inactive=False,
    )
    for department in department_rows:
        department_id = str(department.id)
        parent_id = str(department.parent_id) if department.parent_id else org_id_str
        scopes[("department", department_id)] = _scope_bucket(
            scope_type="department",
            scope_id=department_id,
            scope_name=department.name,
            parent_scope_type="department" if department.parent_id else "organization",
            parent_scope_id=parent_id,
            rate_limit_rpm=department.rate_limit_rpm,
            rate_limit_tpm=department.rate_limit_tpm,
            token_cap=department.budget_cap_tokens,
            credit_cap=department.budget_cap_credits,
            is_inactive=department.deleted_at is not None,
        )
    for team in team_rows:
        team_id = str(team.id)
        scopes[("team", team_id)] = _scope_bucket(
            scope_type="team",
            scope_id=team_id,
            scope_name=team.name,
            parent_scope_type="department",
            parent_scope_id=str(team.department_id),
            rate_limit_rpm=team.rate_limit_rpm,
            rate_limit_tpm=team.rate_limit_tpm,
            token_cap=team.budget_cap_tokens,
            credit_cap=team.budget_cap_credits,
            is_inactive=team.deleted_at is not None,
        )
    for key in key_rows:
        key_id = str(key.id)
        if key.scope_type == "team" and key.team_id:
            parent_scope_type, parent_scope_id = "team", str(key.team_id)
        elif key.scope_type == "department" and key.department_id:
            parent_scope_type, parent_scope_id = "department", str(key.department_id)
        else:
            parent_scope_type, parent_scope_id = "organization", org_id_str
        scopes[("api_key", key_id)] = _scope_bucket(
            scope_type="api_key",
            scope_id=key_id,
            scope_name=key.key_name,
            parent_scope_type=parent_scope_type,
            parent_scope_id=parent_scope_id,
            rate_limit_rpm=key.rate_limit_rpm,
            rate_limit_tpm=key.rate_limit_tpm,
            token_cap=key.budget_cap_tokens,
            credit_cap=key.budget_cap_credits,
            is_inactive=key.revoked_at is not None,
        )

    reserved = aliased(AiQuotaEvent, name="quota_reserved")
    settled = aliased(AiQuotaEvent, name="quota_settled")
    range_start = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)
    range_end = datetime.combine(period_end, datetime.min.time(), tzinfo=UTC)
    rows = (
        await db.execute(
            select(
                reserved.reservation_id,
                reserved.scope_type,
                reserved.scope_id,
                reserved.api_key_id,
                func.coalesce(settled.provider_id, reserved.provider_id).label("provider_id"),
                reserved.reserved_tokens,
                reserved.reserved_credits,
                settled.actual_tokens,
                settled.actual_input_tokens,
                settled.actual_output_tokens,
                settled.outcome,
            )
            .select_from(reserved)
            .outerjoin(
                settled,
                and_(
                    settled.reservation_id == reserved.reservation_id,
                    settled.organization_id == reserved.organization_id,
                    settled.scope_id == reserved.scope_id,
                    settled.scope_type == reserved.scope_type,
                    settled.event_type == "settled",
                ),
            )
            .where(
                reserved.organization_id == org_id_str,
                reserved.event_type == "reserved",
                reserved.created_at >= range_start,
                reserved.created_at < range_end,
            )
        )
    ).all()

    for row in rows:
        scope_key = (str(row.scope_type), str(row.scope_id))
        bucket = scopes.get(scope_key)
        if bucket is None:
            bucket = _scope_bucket(
                scope_type=scope_key[0],
                scope_id=scope_key[1],
                scope_name="（历史范围）",
                parent_scope_type=None,
                parent_scope_id=None,
                rate_limit_rpm=None,
                rate_limit_tpm=None,
                token_cap=None,
                credit_cap=None,
                is_inactive=True,
            )
            scopes[scope_key] = bucket
        has_actual = row.actual_tokens is not None
        usage = bucket["usage"]
        usage["actual_tokens"] += int(row.actual_tokens or 0) if has_actual else 0
        usage["held_unknown_tokens"] += 0 if has_actual else int(row.reserved_tokens or 0)
        usage["credits"] += int(row.reserved_credits or 0)
        usage["requests"] += 1

    _attach_scope_remaining(scopes)
    organization_rows = [row for row in rows if row.scope_type == "organization"]

    provider_ids = {str(row.provider_id) for row in organization_rows if row.provider_id}
    providers_meta: dict[str, dict] = {}
    if provider_ids:
        provider_rows = (
            await db.execute(
                select(LlmProvider.id, LlmProvider.name, LlmProvider.provider_type).where(
                    LlmProvider.id.in_(provider_ids)
                )
            )
        ).all()
        providers_meta = {
            str(provider.id): {
                "provider_id": str(provider.id),
                "provider_name": provider.name,
                "provider_type": provider.provider_type,
            }
            for provider in provider_rows
        }

    unassigned: dict | None = None
    provider_buckets: dict[tuple[str | None, str | None], dict] = {}
    for row in organization_rows:
        raw_key_id = str(row.api_key_id) if row.api_key_id else None
        provider_id = str(row.provider_id) if row.provider_id else None
        if raw_key_id and raw_key_id in keys_meta:
            normalized_key_id = raw_key_id
            bucket = keys_meta[raw_key_id]
        else:
            normalized_key_id = None
            if unassigned is None:
                unassigned = _empty_key_bucket(
                    api_key_id=None,
                    key_name="（未关联 Key）",
                    key_prefix=None,
                    token_cap=None,
                    credit_cap=None,
                    is_revoked=False,
                )
            bucket = unassigned

        has_actual = row.actual_tokens is not None
        input_tokens = int(row.actual_input_tokens or 0)
        output_tokens = int(row.actual_output_tokens or 0)
        total_tokens = int(row.actual_tokens) if has_actual else int(row.reserved_tokens or 0)
        retained_unknown = 0 if has_actual else int(row.reserved_tokens or 0)
        credits = int(row.reserved_credits or 0)
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        bucket["retained_unknown_tokens"] += retained_unknown
        bucket["credits"] += credits
        bucket["request_count"] += 1

        provider_key = (normalized_key_id, provider_id)
        provider_entry = provider_buckets.get(provider_key)
        if provider_entry is None:
            provider_entry = {
                **providers_meta.get(
                    provider_id,
                    {
                        "provider_id": provider_id,
                        "provider_name": "未知",
                        "provider_type": None,
                    },
                ),
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "retained_unknown_tokens": 0,
                "credits": 0,
                "request_count": 0,
            }
            provider_buckets[provider_key] = provider_entry
            bucket["providers"].append(provider_entry)
        provider_entry["input_tokens"] += input_tokens
        provider_entry["output_tokens"] += output_tokens
        provider_entry["total_tokens"] += total_tokens
        provider_entry["retained_unknown_tokens"] += retained_unknown
        provider_entry["credits"] += credits
        provider_entry["request_count"] += 1

    api_keys_list = [
        bucket
        for bucket in keys_meta.values()
        if include_revoked or not bucket["is_revoked"] or bucket["request_count"] > 0
    ]
    if unassigned is not None:
        api_keys_list.append(unassigned)
    for bucket in api_keys_list:
        bucket["providers"].sort(key=lambda item: item["total_tokens"], reverse=True)
        api_key_id = bucket.get("api_key_id")
        scope = scopes.get(("api_key", str(api_key_id))) if api_key_id else None
        bucket["effective_remaining"] = (
            scope["effective_remaining"] if scope is not None else None
        )

    scope_order = {"organization": 0, "department": 1, "team": 2, "api_key": 3}
    scopes_list = sorted(
        scopes.values(),
        key=lambda item: (
            scope_order.get(item["scope_type"], 99),
            item["scope_name"],
            item["scope_id"],
        ),
    )

    return {
        "timezone": "UTC",
        "as_of": as_of.isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "enforcement": {
            "rpm": "redis_atomic",
            "tpm": "redis_atomic",
            "token_budget": "redis_atomic_monthly_token_metered_capabilities",
            "credit_budget": "redis_atomic_monthly_all_ai_calls",
            "usd_budget": "legacy_read_only_not_enforced",
            "durable_ledger": "postgresql_append_only",
        },
        "total_input_tokens": sum(bucket["input_tokens"] for bucket in api_keys_list),
        "total_output_tokens": sum(bucket["output_tokens"] for bucket in api_keys_list),
        "total_tokens": sum(bucket["total_tokens"] for bucket in api_keys_list),
        "retained_unknown_tokens": sum(
            bucket["retained_unknown_tokens"] for bucket in api_keys_list
        ),
        "credits": sum(bucket["credits"] for bucket in api_keys_list),
        "request_count": sum(bucket["request_count"] for bucket in api_keys_list),
        "scopes": scopes_list,
        "api_keys": api_keys_list,
    }
