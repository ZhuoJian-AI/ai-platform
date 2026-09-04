"""Focused tests for the administrator's hierarchical quota report."""

from app.api.budget import _attach_scope_remaining, _scope_bucket


def _scope(
    scope_type: str,
    scope_id: str,
    *,
    parent_scope_type: str | None = None,
    parent_scope_id: str | None = None,
    token_cap: int | None = None,
    credit_cap: int | None = None,
) -> dict:
    return _scope_bucket(
        scope_type=scope_type,
        scope_id=scope_id,
        scope_name=scope_id,
        parent_scope_type=parent_scope_type,
        parent_scope_id=parent_scope_id,
        rate_limit_rpm=None,
        rate_limit_tpm=None,
        token_cap=token_cap,
        credit_cap=credit_cap,
        is_inactive=False,
    )


def test_effective_remaining_uses_shared_parent_balance() -> None:
    scopes = {
        ("organization", "org"): _scope(
            "organization", "org", token_cap=100, credit_cap=10
        ),
        ("department", "dept"): _scope(
            "department",
            "dept",
            parent_scope_type="organization",
            parent_scope_id="org",
            token_cap=80,
            credit_cap=20,
        ),
        ("team", "team"): _scope(
            "team",
            "team",
            parent_scope_type="department",
            parent_scope_id="dept",
        ),
        ("api_key", "key"): _scope(
            "api_key",
            "key",
            parent_scope_type="team",
            parent_scope_id="team",
            token_cap=200,
            credit_cap=100,
        ),
    }
    scopes[("organization", "org")]["usage"].update(
        actual_tokens=70,
        held_unknown_tokens=10,
        credits=7,
        requests=7,
    )
    scopes[("department", "dept")]["usage"].update(
        actual_tokens=5,
        held_unknown_tokens=0,
        credits=1,
        requests=1,
    )
    scopes[("api_key", "key")]["usage"].update(
        actual_tokens=5,
        held_unknown_tokens=0,
        credits=1,
        requests=1,
    )

    _attach_scope_remaining(scopes)

    key = scopes[("api_key", "key")]
    assert key["direct_remaining"] == {
        "monthly_tokens": 195,
        "monthly_credits": 99,
    }
    assert key["effective_remaining"] == {
        "monthly_tokens": 20,
        "monthly_credits": 3,
    }
