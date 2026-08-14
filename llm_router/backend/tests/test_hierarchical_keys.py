"""Tests for permission resolver."""

from decimal import Decimal
from uuid import uuid4

from app.auth.permission_resolver import resolve_effective_permissions
from app.models.api_key import ApiKey
from app.models.department import Department
from app.models.organization import Organization
from app.models.team import Team


def _make_org(**kwargs) -> Organization:
    defaults = {
        "id": uuid4(),
        "name": "Test Org",
        "slug": "test-org",
        "settings": {},
        "rate_limit_rpm": 100,
        "rate_limit_tpm": 100000,
        "budget_cap_usd": Decimal("1000.00"),
    }
    defaults.update(kwargs)
    return Organization(**defaults)


def _make_dept(org_id=None, **kwargs) -> Department:
    defaults = {
        "id": uuid4(),
        "organization_id": org_id or uuid4(),
        "name": "Test Dept",
        "slug": "test-dept",
        "settings": {},
        "rate_limit_rpm": 50,
        "rate_limit_tpm": 50000,
        "budget_cap_usd": Decimal("500.00"),
    }
    defaults.update(kwargs)
    return Department(**defaults)


def _make_team(dept_id=None, org_id=None, **kwargs) -> Team:
    defaults = {
        "id": uuid4(),
        "department_id": dept_id or uuid4(),
        "organization_id": org_id or uuid4(),
        "name": "Test Team",
        "slug": "test-team",
        "settings": {},
        "rate_limit_rpm": 30,
        "rate_limit_tpm": 30000,
        "budget_cap_usd": Decimal("200.00"),
    }
    defaults.update(kwargs)
    return Team(**defaults)


def _make_api_key(**kwargs) -> ApiKey:
    defaults = {
        "id": uuid4(),
        "key_prefix": "lr_sk_org_",
        "key_hash": "fakehash",
        "key_name": "test key",
        "scope_type": "organization",
        "organization_id": uuid4(),
        "allowed_models": [],
        "rate_limit_rpm": None,
        "rate_limit_tpm": None,
        "budget_cap_usd": None,
    }
    defaults.update(kwargs)
    return ApiKey(**defaults)


def test_rate_limit_takes_minimum():
    """速率限制应取所有层级的最小值。"""
    org = _make_org(rate_limit_rpm=100)
    dept = _make_dept(rate_limit_rpm=50)
    team = _make_team(rate_limit_rpm=30)
    key = _make_api_key(rate_limit_rpm=None)

    perms = resolve_effective_permissions(key, org, dept, team)
    assert perms.rate_limit_rpm == 30  # 取最小值


def test_budget_takes_minimum():
    """预算上限应取所有层级的最小值。"""
    org = _make_org(budget_cap_usd=Decimal("1000"))
    dept = _make_dept(budget_cap_usd=Decimal("500"))
    team = _make_team(budget_cap_usd=Decimal("200"))
    key = _make_api_key(budget_cap_usd=Decimal("150"))

    perms = resolve_effective_permissions(key, org, dept, team)
    assert perms.budget_cap_usd == Decimal("150")  # key 级别最低


def test_models_intersection():
    """模型列表应取交集（子级只能缩小范围）。"""
    org = _make_org(settings={"default_models": ["claude-opus-4-8", "claude-sonnet-4-6", "gpt-4o"]})
    dept = _make_dept(settings={"default_models": ["claude-opus-4-8", "claude-sonnet-4-6"]})
    team = _make_team(settings={"default_models": ["claude-sonnet-4-6"]})
    key = _make_api_key(allowed_models=["claude-sonnet-4-6"])

    perms = resolve_effective_permissions(key, org, dept, team)
    assert perms.allowed_models == {"claude-sonnet-4-6"}


def test_wildcard_allows_all():
    """通配符 '*' 应允许所有模型。"""
    org = _make_org(settings={})
    key = _make_api_key(allowed_models=[])

    perms = resolve_effective_permissions(key, org)
    assert "*" in perms.allowed_models


def test_null_inherits_parent():
    """NULL 值应继承父级。"""
    org = _make_org(rate_limit_rpm=100, budget_cap_usd=Decimal("500"))
    key = _make_api_key(rate_limit_rpm=None, budget_cap_usd=None)

    perms = resolve_effective_permissions(key, org)
    assert perms.rate_limit_rpm == 100
    assert perms.budget_cap_usd == Decimal("500")
