"""Execution verification and task-title regression tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.schemas.task import TaskMessageRead
from app.services.message_verification import classify_execution_verification
from app.services.task_service import make_task_title


@pytest.fixture(autouse=True)
def db_engine():
    """These tests are pure and do not require the PostgreSQL fixture."""
    yield


@pytest.mark.parametrize(
    ("traces", "expected"),
    [
        ([{"name": "spreadsheet_tool", "ok": True}], "verified"),
        ([{"name": "a", "ok": True}, {"name": "b", "ok": False}], "partial"),
        ([{"name": "spreadsheet_tool", "ok": False}], "failed"),
    ],
)
def test_execution_verification_uses_real_tool_traces(traces, expected):
    result = classify_execution_verification("完成", {"traces": traces})
    assert result is not None
    assert result["status"] == expected


def test_execution_verification_marks_a_delivered_fallback_as_recovered():
    result = classify_execution_verification(
        "处理完成",
        {
            "traces": [
                {"name": "spreadsheet_tool", "ok": False},
                {"name": "spreadsheet_tool", "ok": True},
                {"name": "workspace_read_file", "ok": True},
            ],
            "artifacts": [{"file_id": "01234567-89ab-4cde-8fab-0123456789ab"}],
        },
    )

    assert result is not None
    assert result == {"status": "recovered", "tool_calls": 3, "succeeded": 2, "failed": 1}


def test_execution_verification_keeps_a_terminal_failure_partial():
    result = classify_execution_verification(
        "仅完成了一部分",
        {
            "traces": [
                {"name": "run_skill_script", "ok": True},
                {"name": "spreadsheet_tool", "ok": False},
            ],
            "artifacts": [{"file_id": "01234567-89ab-4cde-8fab-0123456789ab"}],
        },
    )

    assert result is not None
    assert result["status"] == "partial"


def test_execution_verification_distinguishes_plain_and_legacy_claims():
    assert classify_execution_verification("这是普通问答。", {"traces": []}) is None
    result = classify_execution_verification(
        "文件已生成，file_id: 01234567-89ab-4cde-8fab-0123456789ab",
        {"traces": []},
    )
    assert result is not None
    assert result["status"] == "legacy_unverified"


def test_task_message_read_exposes_derived_verification():
    now = datetime.now(UTC)
    message = TaskMessageRead.model_validate({
        "id": uuid4(), "task_id": uuid4(), "role": "assistant", "content": "处理完成",
        "metadata": {"traces": [{"name": "document_tool", "ok": True}]},
        "created_at": now, "updated_at": now,
    })
    assert message.execution_verification is not None
    assert message.execution_verification.status == "verified"


@pytest.mark.parametrize(
    ("message", "title"),
    [
        ("/bank-process @01234567-89ab-4cde-8fab-0123456789ab 处理这份流水。后续说明", "处理这份流水"),
        ("[附件：流水.xlsx]   请分析 文件", "请分析 文件"),
        ("   ", "新任务"),
    ],
)
def test_make_task_title_removes_invocation_noise(message, title):
    assert make_task_title(message) == title
