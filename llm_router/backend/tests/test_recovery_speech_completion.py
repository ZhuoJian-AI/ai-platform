import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.core.speech_progress import SpeechProgress
from app.agents.graph import nodes
from app.services import assistant_outcomes as outcomes
from app.services import message_speech_service as speech
from app.services import speech_summary


def execution(request_id, status, *, name="update_owner", ok=True):
    return {"requestId": request_id, "name": name, "kind": "enterprise_action",
            "operation": "update", "resultStatus": status, "ok": ok}


def test_one_success_cannot_hide_another_unknown_write():
    rows = [execution("one", "completed"), execution("two", "failed")]
    rows[-1]["executionOutcome"] = "unknown"
    assert [r["status"] for r in outcomes.operation_outcomes(rows)] == ["completed", "unknown"]
    assert outcomes.unresolved_writes(rows)[0]["requestId"] == "two"


def test_correction_resolves_provisional_error_but_preserves_other_operation():
    rows = [execution("", "retryable_error", ok=False), execution("other", "pending"),
            execution("corrected", "completed")]
    assert [r["requestId"] for r in outcomes.operation_outcomes(rows)] == ["other", "corrected"]
    rows.append(execution("other", "completed", name="resume_action_alias"))
    assert outcomes.unresolved_writes(rows) == []


def test_file_failure_is_separate_from_successful_write():
    state = {"business_tool_executions": [execution("one", "completed")], "_file_delivery_required": True}
    assert [r["status"] for r in outcomes.final_outcomes(state, [])] == ["completed", "not_completed"]
    artifact = {"file_id": "new-file", "version_id": "new-version"}
    assert outcomes.final_outcomes(state, [artifact])[-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_summary_uses_gateway_without_tools_or_private_reasoning(monkeypatch):
    chat = AsyncMock(return_value=SimpleNamespace(content="订单已修改，文件保存失败。", reasoning_content="secret"))
    monkeypatch.setattr(speech_summary.model_gateway, "chat", chat)
    cu = SimpleNamespace(organization_id=uuid4(), department_id=None)
    result = await speech_summary.summarize(None, cu, "<think>private</think>订单已修改。文件保存失败。")
    assert result == "内容摘要：订单已修改，文件保存失败。"
    assert "private" not in str(chat.call_args)
    assert "tools" not in chat.call_args.kwargs
    assert chat.call_args.args[2] == "default"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty", "too-long", "network", "private-only"])
async def test_summary_failure_never_claims_success_or_repeats_business(monkeypatch, failure):
    values = {"empty": "", "too-long": "很多" * 400, "private-only": "<think>secret</think>"}
    chat = AsyncMock(return_value=SimpleNamespace(content=values.get(failure)))
    if failure == "network":
        chat.side_effect = RuntimeError("provider secret")
    monkeypatch.setattr(speech_summary.model_gateway, "chat", chat)
    result = await speech_summary.summarize(None, SimpleNamespace(organization_id=uuid4()), "真实结果")
    assert result == speech_summary.FALLBACK
    assert "secret" not in result
    assert chat.await_count == 1


def test_stream_summary_waits_for_final_failure_and_keeps_order():
    progress = SpeechProgress()
    start = "查询已完成。" * 100
    first = progress.update(start, ready=True)
    assert all(not row.get("summaryRequired") for row in first)
    final = progress.update(start + "但文件保存失败。", ready=True, final=True)
    assert final[0]["summaryRequired"]
    assert final[0]["text"].endswith("文件保存失败。")
    assert final[0]["segmentIndex"] == len(first)
    assert progress.update(start, ready=True, final=True) == []


def test_repeat_operation_requires_explicit_confirmation_title():
    action = SimpleNamespace(operation="create", requires_confirmation=False, name="新建订单", input_schema={})
    entry = {"kind": "enterprise_action", "action": action, "repeat_operation": True}
    assert nodes._assistant_tool_requires_approval("repeat", entry)
    metadata = nodes._assistant_confirmation_metadata("repeat", entry)
    assert "再次执行" in json.dumps(metadata, ensure_ascii=False)


@pytest.mark.asyncio
async def test_playback_summary_is_lazy_and_repeated_click_reuses_audio(monkeypatch):
    cu = SimpleNamespace(id=str(uuid4()), organization_id=uuid4(), department_id=None)
    voice = SimpleNamespace(id=uuid4(), updated_at=datetime.now(UTC),
                            provider_voice_id="standard", voice_type="builtin")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
    monkeypatch.setattr(speech.audio, "list_visible_voices", AsyncMock(return_value=[voice]))
    monkeypatch.setattr(speech.audio.model_gateway, "resolve_deployment", AsyncMock(return_value=object()))
    summarize = AsyncMock(return_value="业务已完成，文件尚未保存。")
    monkeypatch.setattr(speech_summary, "summarize", summarize)
    create = AsyncMock()
    monkeypatch.setattr(speech.audio, "_create_job", create)
    content = "业务结果。" * 200
    assert len(speech.message_segments(content)) == 1
    summarize.assert_not_awaited()
    binding = {"task_id": "task", "message_id": "message", "content_version": speech.content_version(content)}
    await speech.create_bound_speech(db, cu, content, binding, summary_required=True)
    assert create.call_args.kwargs["params"]["text"] == "业务已完成，文件尚未保存。"
    assert create.call_args.kwargs["params"]["content_version"] == binding["content_version"]
    cached = SimpleNamespace(status="succeeded", output_file_ref="oss://test/audio",
        params={"cleanup_after": (datetime.now(UTC) + timedelta(hours=1)).isoformat()})
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: cached)
    assert await speech.create_bound_speech(db, cu, content, binding, summary_required=True) is cached
    assert summarize.await_count == create.await_count == 1
