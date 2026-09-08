"""Pure safety and determinism checks for database release audit scripts."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType

import pytest
import pytest_asyncio

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest_asyncio.fixture(autouse=True)
async def db_engine() -> AsyncIterator[None]:
    """These script tests must never provision or connect to PostgreSQL."""

    yield None


def _load_script(module_name: str, filename: str) -> ModuleType:
    path = REPOSITORY_ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


SNAPSHOT = _load_script("capture_protected_database_snapshot_test", "capture_protected_database_snapshot.py")
PREFLIGHT = _load_script("report_retired_schema_preflight_test", "report_retired_schema_preflight.py")


@pytest.mark.parametrize("module", [SNAPSHOT, PREFLIGHT])
def test_asyncpg_urls_are_normalized_without_printing_credentials(module: ModuleType) -> None:
    assert module._database_url("postgresql+asyncpg://user:secret@localhost/db") == (
        "postgresql://user:secret@localhost/db"
    )


@pytest.mark.parametrize("module", [SNAPSHOT, PREFLIGHT])
def test_remote_database_requires_explicit_read_only_acknowledgement(module: ModuleType) -> None:
    with pytest.raises(ValueError, match="--allow-remote-read-only"):
        module._assert_connection_scope(
            "postgresql://user:secret@database.example/db",
            allow_remote=False,
        )
    module._assert_connection_scope(
        "postgresql://user:secret@database.example/db",
        allow_remote=True,
    )
    module._assert_connection_scope(
        "postgresql://user:secret@127.0.0.1/db",
        allow_remote=False,
    )


def test_snapshot_hashes_are_deterministic_and_order_sensitive() -> None:
    records = [{"id": "1", "value": "甲"}, {"id": "2", "value": "乙"}]
    first_hash, first_count = SNAPSHOT._digest_records(records)
    repeated_hash, repeated_count = SNAPSHOT._digest_records(records)
    reversed_hash, reversed_count = SNAPSHOT._digest_records(reversed(records))

    assert (first_hash, first_count) == (repeated_hash, repeated_count)
    assert first_count == reversed_count == 2
    assert first_hash != reversed_hash


def test_release_inventory_keeps_core_data_and_conditional_history_explicit() -> None:
    assert {
        "workspace_files",
        "workspace_file_versions",
        "rag_documents",
        "task_messages",
        "agent_run_events",
        "skill_versions",
        "enterprise_applications",
        "ecs_runtimes",
    }.issubset(set(SNAPSHOT.PROTECTED_TABLES))
    assert "teams" in PREFLIGHT.RETIRED_TABLES
    assert "enterprise_application_tool_bindings" in PREFLIGHT.RETIRED_TABLES
    assert PREFLIGHT.CONDITIONAL_RETIRED_TABLES == ("tool_call_logs",)
