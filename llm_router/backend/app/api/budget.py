"""Budget usage API — token consumption per API Key, broken down by provider.

预算消耗统一以 token 计量。本接口实时聚合 audit_logs，按 API Key × Provider 维度统计
输入/输出 token 消耗，无需后台预聚合任务。

已删除（撤销）的 API Key 默认不展示，可通过 include_revoked=true 查看。
"""

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_org_access
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.llm_provider import LlmProvider

router = APIRouter()


def _month_range(ref: date | None = None) -> tuple[date, date]:
    """返回 ref 所在自然月的 [起始日, 下月起始日)。"""
    today = ref or date.today()
    period_start = today.replace(day=1)
    if today.month == 12:
        period_end = date(today.year + 1, 1, 1)
    else:
        period_end = date(today.year, today.month + 1, 1)
    return period_start, period_end


@router.get("/organizations/{org_id}/budget/usage")
async def get_budget_usage(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
    start_date: date | None = Query(None, description="起始日期（含），默认当月 1 日"),
    end_date: date | None = Query(None, description="结束日期（不含），默认下月 1 日"),
    include_revoked: bool = Query(False, description="是否包含已删除（撤销）的 API Key"),
) -> dict:
    """查询组织在指定周期内的 token 消耗，按 API Key × Provider 聚合。

    - 顶层为周期内总输入/输出 token、请求数
    - api_keys: 每个 Key 的 token 汇总 + providers 明细（展开行）
    - 默认排除已删除（revoked_at 非空）的 Key 及其用量；include_revoked=true 时返回
    """
    period_start, period_end = _month_range()
    if start_date:
        period_start = start_date
    if end_date:
        period_end = end_date

    org_id_str = str(org_id)

    # ── 取该组织下所有 API Key 的元数据 ──
    key_rows = (
        await db.execute(
            select(
                ApiKey.id,
                ApiKey.key_name,
                ApiKey.key_prefix,
                ApiKey.budget_cap_tokens,
                ApiKey.revoked_at,
            ).where(ApiKey.organization_id == org_id_str)
        )
    ).all()

    revoked_ids: set[str] = set()
    keys_meta: dict[str, dict] = {}
    for k in key_rows:
        kid = str(k.id)
        is_revoked = k.revoked_at is not None
        if is_revoked:
            revoked_ids.add(kid)
            if not include_revoked:
                continue  # 默认排除已删除 Key
        keys_meta[kid] = {
            "api_key_id": kid,
            "key_name": k.key_name,
            "key_prefix": k.key_prefix,
            "budget_cap_tokens": k.budget_cap_tokens,
            "is_revoked": is_revoked,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "request_count": 0,
            "providers": [],
        }

    # ── 按 api_key × provider 聚合 audit_logs ──
    conditions = [
        AuditLog.organization_id == org_id_str,
        AuditLog.created_at >= datetime.combine(period_start, datetime.min.time()),
        AuditLog.created_at < datetime.combine(period_end, datetime.min.time()),
    ]
    # 默认排除已删除 Key 的历史用量
    if not include_revoked and revoked_ids:
        conditions.append(~AuditLog.api_key_id.in_(revoked_ids))

    stmt = (
        select(
            AuditLog.api_key_id,
            AuditLog.provider_id,
            func.coalesce(func.sum(AuditLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AuditLog.output_tokens), 0).label("output_tokens"),
            func.count().label("request_count"),
        )
        .where(*conditions)
        .group_by(AuditLog.api_key_id, AuditLog.provider_id)
    )
    rows = (await db.execute(stmt)).all()

    # ── 取相关 Provider 元数据 ──
    provider_ids = {str(r.provider_id) for r in rows if r.provider_id}
    providers_meta: dict[str, dict] = {}
    if provider_ids:
        prov_rows = (
            await db.execute(
                select(LlmProvider.id, LlmProvider.name, LlmProvider.provider_type).where(
                    LlmProvider.id.in_(provider_ids)
                )
            )
        ).all()
        providers_meta = {
            str(p.id): {"provider_id": str(p.id), "provider_name": p.name, "provider_type": p.provider_type}
            for p in prov_rows
        }

    # ── 组装：把聚合行挂到对应 Key 下 ──
    # 注意：AuditLog.api_key_id 经 asyncpg 返回为 uuid.UUID，需统一转 str 再匹配 keys_meta。
    # api_key_id 为 NULL（请求未识别 Key）归到 "<unassigned>"。
    unassigned: dict | None = None
    for r in rows:
        input_tokens = int(r.input_tokens or 0)
        output_tokens = int(r.output_tokens or 0)
        total_tokens = input_tokens + output_tokens
        akid = str(r.api_key_id) if r.api_key_id else None
        pid = str(r.provider_id) if r.provider_id else None

        provider_entry = {
            **providers_meta.get(
                pid,
                {"provider_id": pid, "provider_name": "未知", "provider_type": None},
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "request_count": int(r.request_count or 0),
        }

        if akid and akid in keys_meta:
            bucket = keys_meta[akid]
        else:
            if unassigned is None:
                unassigned = {
                    "api_key_id": None,
                    "key_name": "（未关联 Key）",
                    "key_prefix": None,
                    "budget_cap_tokens": None,
                    "is_revoked": False,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "request_count": 0,
                    "providers": [],
                }
            bucket = unassigned

        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        bucket["request_count"] += int(r.request_count or 0)
        bucket["providers"].append(provider_entry)

    api_keys_list = list(keys_meta.values())
    if unassigned is not None:
        api_keys_list.append(unassigned)

    # 每个 Key 的 providers 按总 token 降序
    for k in api_keys_list:
        k["providers"].sort(key=lambda p: p["total_tokens"], reverse=True)

    total_input = sum(k["input_tokens"] for k in api_keys_list)
    total_output = sum(k["output_tokens"] for k in api_keys_list)

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "request_count": sum(k["request_count"] for k in api_keys_list),
        "api_keys": api_keys_list,
    }
