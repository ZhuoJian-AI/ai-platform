"""Scoped professional-AI contract and worker tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import subsystem_ai_service
from app.services.subsystem_integration_service import (
    _normalize_platform_ai_capability,
)
from app.workers import multimodal_worker

RESULT_SCHEMA = {
    "type": "object",
    "properties": {"opinion": {"type": "string"}},
    "required": ["opinion"],
    "additionalProperties": False,
}


def test_manifest_specialist_ai_requires_query_confirmation_and_real_schema():
    declaration = {
        "type": "vision.ocr",
        "inputKinds": ["image"],
        "humanConfirmation": "required",
    }
    assert _normalize_platform_ai_capability(
        "sample.ocr",
        declaration,
        contract_revision="2.5",
        operation="query",
        ai_enabled=True,
        result_schema=RESULT_SCHEMA,
    ) == declaration

    invalid_cases = [
        {"contract_revision": "2.4"},
        {"operation": "update"},
        {"ai_enabled": False},
        {"result_schema": {"type": "object"}},
        {"value": {**declaration, "humanConfirmation": "optional"}},
        {"value": {**declaration, "inputKinds": ["audio"]}},
    ]
    for overrides in invalid_cases:
        kwargs = {
            "value": declaration,
            "contract_revision": "2.5",
            "operation": "query",
            "ai_enabled": True,
            "result_schema": RESULT_SCHEMA,
            **overrides,
        }
        with pytest.raises(ValueError):
            _normalize_platform_ai_capability("sample.ocr", **kwargs)


def test_structured_specialist_result_is_schema_checked():
    draft, confidence, warnings = subsystem_ai_service.parse_structured_result(
        '{"result":{"opinion":"袖长增加 2cm"},"confidence":0.91,"warnings":["日期较模糊"]}',
        RESULT_SCHEMA,
    )
    assert draft == {"opinion": "袖长增加 2cm"}
    assert confidence == 0.91
    assert warnings == ["日期较模糊"]

    with pytest.raises(ValueError, match="Schema"):
        subsystem_ai_service.parse_structured_result(
            '{"result":{"unknown":true},"confidence":1,"warnings":[]}',
            RESULT_SCHEMA,
        )
    with pytest.raises(ValueError, match="confidence"):
        subsystem_ai_service.parse_structured_result(
            '{"result":{"opinion":"x"},"confidence":2,"warnings":[]}',
            RESULT_SCHEMA,
        )
    with pytest.raises(ValueError, match="结构化 result"):
        subsystem_ai_service.parse_structured_result(
            '{"result":{"opinion":"x"},"confidence":1,"warnings":[],"writeNow":true}',
            RESULT_SCHEMA,
        )


@pytest.mark.asyncio
async def test_worker_returns_reviewable_draft_and_rechecks_access(monkeypatch, tmp_path):
    checks = 0

    async def current_access(_db, _job):
        nonlocal checks
        checks += 1
        current = SimpleNamespace(department_id=None)
        action = SimpleNamespace(result_schema=RESULT_SCHEMA)
        return current, action, {}, "text.extract"

    async def safe_scan(*_args, **_kwargs):
        return SimpleNamespace(blocked=False, redacted_text=None)

    async def chat(*_args, **kwargs):
        assert kwargs["request_id"].endswith(":structure:1")
        assert "非可信业务数据" in kwargs["system_prompt"]
        assert kwargs["tool_choice"] == "submit_specialist_draft"
        return SimpleNamespace(
            content="",
            reasoning_content=None,
            tool_calls=[{
                "name": "submit_specialist_draft",
                "arguments": '{"result":{"opinion":"已识别意见"},"confidence":0.8,"warnings":[]}',
            }],
            usage={"input_tokens": 10, "output_tokens": 8},
            model_served="test-model",
        )

    monkeypatch.setattr(multimodal_worker, "_current_specialist_access", current_access)
    monkeypatch.setattr(multimodal_worker, "scan_request", safe_scan)
    monkeypatch.setattr(multimodal_worker, "scan_response", safe_scan)
    monkeypatch.setattr(multimodal_worker.model_gateway, "chat", chat)

    job = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        request_id="request-01234567",
        params={
            "applicationId": str(uuid4()),
            "moduleKey": "sample",
            "pageKey": "sample.review",
            "actionKey": "sample.extract",
            "instruction": "提取批样意见",
            "context": {"recordId": "A-1"},
            "textInput": "袖长增加 2cm",
            "inputObjects": [],
        },
    )
    payload = await multimodal_worker._process_specialist(None, job, tmp_path)

    assert checks == 2
    assert payload["result"]["draft"] == {"opinion": "已识别意见"}
    assert payload["result"]["requiresHumanConfirmation"] is True
    assert payload["result"]["provenance"]["actionKey"] == "sample.extract"
