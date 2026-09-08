"""Regression tests for precise employee persistence error reporting."""

import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.api.users import _user_integrity_http_error
from app.utils.integrity_errors import IntegrityFailure, classify_integrity_error


@pytest_asyncio.fixture(autouse=True)
async def db_engine():
    """This module tests pure classification and must not provision PostgreSQL."""

    yield None


class _DriverError(Exception):
    def __init__(
        self,
        *,
        sqlstate: str,
        constraint_name: str | None = None,
        column_name: str | None = None,
    ) -> None:
        super().__init__("redacted driver failure")
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name
        self.column_name = column_name


def test_classify_nested_asyncpg_diagnostics() -> None:
    driver = _DriverError(sqlstate="23505", constraint_name="uq_user_org_username")
    wrapper = RuntimeError("wrapper")
    wrapper.__cause__ = driver
    exc = IntegrityError("INSERT INTO users ...", {"password_hash": "secret"}, wrapper)

    failure = classify_integrity_error(exc)

    assert failure == IntegrityFailure(
        sqlstate="23505",
        constraint_name="uq_user_org_username",
        column_name=None,
    )


def test_only_username_constraint_is_reported_as_duplicate() -> None:
    verified = _user_integrity_http_error(
        IntegrityFailure(sqlstate="23505", constraint_name="uq_user_org_username"),
        username="alice",
    )
    unrelated = _user_integrity_http_error(
        IntegrityFailure(sqlstate="23505", constraint_name="uq_user_role"),
        username="alice",
    )

    assert verified.status_code == 409
    assert verified.detail == "用户名“alice”已存在，请换一个用户名"
    assert unrelated.status_code == 500
    assert unrelated.detail == "员工保存失败，请稍后重试"


def test_foreign_key_not_null_and_check_errors_are_actionable() -> None:
    foreign_key = _user_integrity_http_error(
        IntegrityFailure(sqlstate="23503", constraint_name="users_department_id_fkey"),
        username=None,
    )
    not_null = _user_integrity_http_error(
        IntegrityFailure(sqlstate="23502", column_name="role"),
        username=None,
    )
    check = _user_integrity_http_error(
        IntegrityFailure(sqlstate="23514", constraint_name="ck_user_membership"),
        username=None,
    )

    assert (foreign_key.status_code, foreign_key.detail) == (
        422,
        "关联的部门或角色不存在，请刷新后重试",
    )
    assert (not_null.status_code, not_null.detail) == (422, "员工资料缺少必填字段：role")
    assert (check.status_code, check.detail) == (422, "员工资料不符合系统约束，请检查后重试")
