import pytest

from app.services.assistant_recovery_context import historical_tool_references


@pytest.mark.parametrize("status,ok,outcome,expected", [
    ("completed", True, "", "completed"),
    ("pending", True, "", "needs_confirmation"),
    ("failed", False, "unknown", "unknown"),
    ("executing", True, "", "in_progress"),
    ("failed", False, "", "not_completed"),
    ("completed", False, "", "not_completed"),
    ("", True, "", "unverified"),
])
def test_history_preserves_execution_state(status, ok, outcome, expected):
    result = historical_tool_references([{
        "resultStatus": status, "ok": ok, "executionOutcome": outcome,
        "requestId": "stable-request", "params": {"secret": "not-for-context"},
    }])[0]
    assert result["recoveryState"] == expected
    assert result["requestId"] == "stable-request"
    assert "params" not in result


def test_history_keeps_recent_outcomes_and_tolerates_old_metadata():
    assert historical_tool_references(None) == []
    assert historical_tool_references({"ok": True}) == []
    refs = historical_tool_references([None] + [{"toolCallId": str(i), "ok": True} for i in range(25)])
    assert len(refs) == 20
    assert refs[0]["toolCallId"] == "5"
    assert refs[-1]["recoveryState"] == "unverified"
