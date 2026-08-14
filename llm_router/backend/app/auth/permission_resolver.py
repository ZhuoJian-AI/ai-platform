"""Permission resolver — cascade permissions from org → dept → team → key."""

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.api_key import ApiKey
from app.models.department import Department
from app.models.organization import Organization
from app.models.team import Team


@dataclass
class EffectivePermissions:
    """最终生效的权限配置。"""
    allowed_models: set[str] = field(default_factory=lambda: {"*"})
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    # 预算上限以 token 计（与 budget_cap_usd 并存；当前预算消耗以 token 为准）
    budget_cap_tokens: int | None = None


def resolve_effective_permissions(
    api_key: ApiKey,
    org: Organization,
    dept: Department | None = None,
    team: Team | None = None,
) -> EffectivePermissions:
    """级联计算最终权限。

    规则:
    - 模型列表: 子级与父级取交集（子级只能缩小范围）
    - 速率限制: 取所有层级的最小值（子级不能突破父级上限）
    - 预算上限: 取所有层级的最小值
    """
    # ── 模型列表 (交集) ──
    model_sets: list[set[str]] = []
    _append_models(model_sets, org.settings.get("default_models"))
    if dept:
        _append_models(model_sets, dept.settings.get("default_models"))
    if team:
        _append_models(model_sets, team.settings.get("default_models"))
    _append_models(model_sets, api_key.allowed_models)

    if model_sets:
        # 需要考虑通配符 "*" 的特殊情况
        if any("*" in s for s in model_sets):
            # 如果任一层允许全部，则交集取决于其他层的限制
            non_wildcard = [s for s in model_sets if "*" not in s]
            if non_wildcard:
                allowed_models = set.intersection(*non_wildcard)
            else:
                allowed_models = {"*"}
        else:
            allowed_models = set.intersection(*model_sets)
    else:
        allowed_models = {"*"}

    # ── 速率限制 (最小有效值) ──
    rpm_candidates = [v for v in [
        api_key.rate_limit_rpm,
        team.rate_limit_rpm if team else None,
        dept.rate_limit_rpm if dept else None,
        org.rate_limit_rpm,
    ] if v is not None]
    effective_rpm = min(rpm_candidates) if rpm_candidates else None

    tpm_candidates = [v for v in [
        api_key.rate_limit_tpm,
        team.rate_limit_tpm if team else None,
        dept.rate_limit_tpm if dept else None,
        org.rate_limit_tpm,
    ] if v is not None]
    effective_tpm = min(tpm_candidates) if tpm_candidates else None

    # ── 预算上限 (最小有效值) ──
    budget_candidates = [v for v in [
        api_key.budget_cap_usd,
        team.budget_cap_usd if team else None,
        dept.budget_cap_usd if dept else None,
        org.budget_cap_usd,
    ] if v is not None]
    effective_budget = min(budget_candidates) if budget_candidates else None

    # ── 预算上限（以 token 计，最小有效值）──
    token_candidates = [v for v in [
        api_key.budget_cap_tokens,
        team.budget_cap_tokens if team else None,
        dept.budget_cap_tokens if dept else None,
        org.budget_cap_tokens,
    ] if v is not None]
    effective_budget_tokens = min(token_candidates) if token_candidates else None

    return EffectivePermissions(
        allowed_models=allowed_models,
        rate_limit_rpm=effective_rpm,
        rate_limit_tpm=effective_tpm,
        budget_cap_usd=effective_budget,
        budget_cap_tokens=effective_budget_tokens,
    )


def _append_models(sets: list[set[str]], models) -> None:
    """将模型列表转换为集合并追加。"""
    if models is None:
        return
    if isinstance(models, list):
        s = set(models)
        if s:  # 忽略空列表（表示"未设置"，不是"无权限"）
            sets.append(s)
    elif isinstance(models, str):
        sets.append({models})
