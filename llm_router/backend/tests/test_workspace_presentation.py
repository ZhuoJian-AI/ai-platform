"""Friendly workspace presentation and page-context contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.task import TaskRunRequest
from app.services.task_service import _match_excerpt, make_task_title
from app.services.workspace_presentation_backfill import backfill_workspace_presentations
from app.utils.workspace_presentation import (
    artifacts_from_traces,
    clean_display_name,
    enrich_metadata,
    presentation_dict,
)


@pytest.fixture(autouse=True)
def db_engine():
    """These tests are pure and do not require the PostgreSQL fixture."""
    yield


def test_managed_output_uses_friendly_name_without_mutating_path() -> None:
    path = "技能输出/01234567-89ab-4cde-8fab-0123456789ab/20260827-112050-706397ac-爱法贝经营数据.xlsx"

    assert clean_display_name(path) == "爱法贝经营数据.xlsx"
    assert presentation_dict(path)["source_task_id"] == "01234567-89ab-4cde-8fab-0123456789ab"


def test_metadata_enrichment_is_idempotent() -> None:
    created = datetime(2026, 8, 27, 11, 20, tzinfo=UTC)
    first = enrich_metadata(
        "平台工具输出/01234567-89ab-4cde-8fab-0123456789ab/20260827-112050-acde1234-汇报.pdf",
        {"binary": True},
        created_at=created,
        source_task_title="生成经营汇报",
    )

    assert enrich_metadata("ignored/汇报.pdf", first, created_at=created) == first
    assert first["display_name"] == "汇报.pdf"
    assert first["source_kind"] == "platform_tool"
    assert first["source_task_title"] == "生成经营汇报"


@pytest.mark.asyncio
async def test_backfill_command_is_repeatable() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        path="技能输出/01234567-89ab-4cde-8fab-0123456789ab/20260827-112050-acde1234-汇报.pdf",
        metadata_={},
        created_at=datetime(2026, 8, 27, 11, 20, tzinfo=UTC),
    )

    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

    class FakeDb:
        async def execute(self, statement):
            return Result([row] if "workspace_files" in str(statement) else [])

        async def flush(self):
            return None

    db = FakeDb()
    first = await backfill_workspace_presentations(db)  # type: ignore[arg-type]
    second = await backfill_workspace_presentations(db)  # type: ignore[arg-type]

    assert first["updated"] == 1
    assert second["updated"] == 0
    assert second["unchanged"] == 1


def test_structured_artifacts_hide_internal_path_from_display_name() -> None:
    traces = [{
        "category": "skill",
        "name": "run_skill_script",
        "ok": True,
        "result": '{"outputs":[{"file_id":"01234567-89ab-4cde-8fab-0123456789ab",'
                  '"display_name":"爱法贝经营方案.docx"}]}',
    }]
    artifacts = artifacts_from_traces(
        traces,
        task_id="11111111-1111-4111-8111-111111111111",
        task_title="生成经营方案",
        executed_skills=[{"id": "skill-1", "name": "经营文档工厂", "version_no": 3}],
    )

    assert artifacts == [{
        "file_id": "01234567-89ab-4cde-8fab-0123456789ab",
        "display_name": "爱法贝经营方案.docx",
        "mime_type": None,
        "size": None,
        "parse_status": None,
        "source": {
            "kind": "skill",
            "task_id": "11111111-1111-4111-8111-111111111111",
            "task_title": "生成经营方案",
            "skill_id": "skill-1",
            "skill_display_name": "经营文档工厂",
            "skill_version": 3,
        },
        "workspace_path": None,
    }]


def test_task_title_and_search_excerpt_are_user_facing() -> None:
    title = make_task_title(
        "/office-suite @01234567-89ab-4cde-8fab-0123456789ab "
        "请生成一份包含生产、设计、商品、销售协同数据的季度经营分析报告以及后续行动计划"
    )

    assert len(title) <= 36
    assert "01234567" not in title
    assert title.endswith("…")
    assert _match_excerpt(
        "前文很多内容，工厂进度发生异常，需要设计部确认。", "工厂进度",
    ) == "前文很多内容，工厂进度发生异常，需要设计部确认。"


def test_iframe_bridge_page_context_validation() -> None:
    request = TaskRunRequest(
        message="分析当前款号",
        page_context={
            "application_slug": "garment-production-collaboration",
            "bridge_version": 1,
            "module_key": "factory_progress",
            "filters": {"season": "26秋"},
            "selection": {"id": "FP-1"},
            "data_version": 3,
        },
    )
    assert request.page_context["bridge_version"] == 1
    assert request.page_context["data_version"] == 3

    with pytest.raises(ValidationError, match="unsupported iframe bridge version"):
        TaskRunRequest(message="bad", page_context={"bridge_version": 2})

    with pytest.raises(ValidationError, match="invalid iframe bridge field"):
        TaskRunRequest(message="bad", page_context={"bridge_version": 1, "filters": []})

    with pytest.raises(ValidationError, match="invalid iframe bridge field: data_version"):
        TaskRunRequest(message="bad", page_context={"bridge_version": 1, "data_version": float("nan")})
