"""Safe helpers for classifying database integrity failures.

The HTTP layer must not infer a business conflict from the mere fact that
SQLAlchemy raised :class:`IntegrityError`.  PostgreSQL exposes a SQLSTATE and,
for constraint violations, the exact constraint/column on the nested driver
exception.  Only those machine-readable attributes are surfaced here; raw SQL
or bound parameters are deliberately excluded from logs and client errors.
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError


@dataclass(frozen=True, slots=True)
class IntegrityFailure:
    sqlstate: str | None = None
    constraint_name: str | None = None
    column_name: str | None = None


def classify_integrity_error(exc: IntegrityError) -> IntegrityFailure:
    """Extract PostgreSQL diagnostics from SQLAlchemy/asyncpg wrappers."""

    sqlstate: str | None = None
    constraint_name: str | None = None
    column_name: str | None = None
    pending: list[BaseException | None] = [exc]
    seen: set[int] = set()

    while pending:
        current = pending.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))

        if sqlstate is None:
            sqlstate = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if constraint_name is None:
            constraint_name = getattr(current, "constraint_name", None)
        if column_name is None:
            column_name = getattr(current, "column_name", None)

        driver_error = getattr(current, "orig", None)
        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        pending.extend((driver_error, cause, context))

    return IntegrityFailure(
        sqlstate=str(sqlstate) if sqlstate else None,
        constraint_name=str(constraint_name) if constraint_name else None,
        column_name=str(column_name) if column_name else None,
    )
