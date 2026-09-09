"""Scoped professional-AI contract and worker tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.graph import nodes
from app.services import platform_tool_registry, subsystem_ai_service
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


@pytest.fixture(autouse=True)
def db_engine():
    """The specialist contract tests are DB-free and use explicit fakes."""
    yield


def test_specialist_tool_is_stable_and_keeps_provider_details_hidden():
    name = nodes._subsystem_specialist_tool_name("alphabet_factory_progress_extract_images")
    assert name == nodes._subsystem_specialist_tool_name("alphabet_factory_progress_extract_images")
    assert len(name) <= 64
    schema = nodes._subsystem_specialist_parameters(
        {"type": "vision.ocr", "inputKinds": ["image"], "humanConfirmation": "required"}
    )
    assert schema["required"] == ["instruction", "input_file_ids"]
    serialized = str(schema)
    assert "provider" not in serialized and "api_key" not in serialized and "base_url" not in serialized


def test_manifest_capability_is_resolved_from_the_bound_action_only():
    declaration = {
        "type": "text.extract",
        "inputKinds": ["text"],
        "humanConfirmation": "required",
    }
    application = SimpleNamespace(
        integration=SimpleNamespace(
            manifest={
                "modules": [{
                    "moduleKey": "sample",
                    "actions": [{"actionKey": "sample.extract", "platformAiCapability": declaration}],
                }]
            }
        )
    )
    assert subsystem_ai_service.manifest_capability(application, "sample", "sample.extract") == declaration
    assert subsystem_ai_service.manifest_capability(application, "sample", "sample.other") is None


@pytest.mark.asyncio
async def test_unified_assistant_executes_specialist_into_the_same_tool_loop(monkeypatch):
    class FakeDb:
        async def flush(self):
            return None

    async def process(_db, _job, _directory):
        return {
            "result": {
                "draft": {"opinion": "袖长增加 2cm"},
                "confidence": 0.9,
                "warnings": [],
                "requiresHumanConfirmation": True,
            },
            "usage": {"input_tokens": 12, "output_tokens": 8},
        }

    async def purge(_job):
        return True

    monkeypatch.setattr(multimodal_worker, "_process_specialist", process)
    monkeypatch.setattr(subsystem_ai_service, "purge_inputs", purge)
    job = SimpleNamespace(
        status="queued",
        started_at=None,
        finished_at=None,
        result={},
        usage={},
        error_category=None,
        error_detail=None,
    )
    result = await subsystem_ai_service.execute_run_inline(FakeDb(), job)
    assert result is job
    assert job.status == "succeeded"
    assert job.result["draft"] == {"opinion": "袖长增加 2cm"}
    assert job.usage == {"input_tokens": 12, "output_tokens": 8}


@pytest.mark.asyncio
async def test_authorized_page_registers_specialist_as_a_main_brain_tool(monkeypatch):
    application_id = uuid4()
    organization_id = uuid4()
    declaration = {
        "type": "text.extract",
        "inputKinds": ["text", "json"],
        "humanConfirmation": "required",
    }
    application = SimpleNamespace(
        id=application_id,
        organization_id=organization_id,
        assistant_enabled=True,
        integration=SimpleNamespace(
            manifest={
                "modules": [{
                    "moduleKey": "style",
                    "actions": [{"actionKey": "style.extract", "platformAiCapability": declaration}],
                }]
            }
        ),
    )
    action = SimpleNamespace(
        module_key="style",
        action_key="style.extract",
        operation="query",
        name="抽取款号资料",
        description="从款号文字中抽取结构化资料",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        result_schema=RESULT_SCHEMA,
        requires_confirmation=False,
    )
    user = SimpleNamespace(organization_id=organization_id, department_id=None)

    async def active_names(_db):
        return set()

    async def get_application(_db, _application_id):
        return application

    async def list_actions(*_args, **_kwargs):
        return [action]

    async def empty_index(*_args, **_kwargs):
        return {"pages": [], "actions": [], "bindings": []}

    async def no_image_generation(*_args, **_kwargs):
        return None

    async def no_model_capabilities(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(platform_tool_registry, "active_platform_tool_names", active_names)
    monkeypatch.setattr(nodes.enterprise_application_service, "get_application", get_application)
    monkeypatch.setattr(nodes.subsystem_action_service, "list_actions_for_user", list_actions)
    monkeypatch.setattr(nodes.subsystem_action_service, "action_tool_name", lambda *_args: "garment_extract")
    monkeypatch.setattr(nodes.business_assistant_orchestration, "build_enterprise_capability_index", empty_index)
    monkeypatch.setattr(nodes.multimodal_service, "resolve_image_generation", no_image_generation)
    monkeypatch.setattr(
        nodes._builtin_tools.model_capability_tools,
        "model_capability_availability",
        no_model_capabilities,
    )
    monkeypatch.setattr(nodes, "_builtin_tool_defs", lambda **_kwargs: [])

    tools, registry = await nodes._build_tools(
        None,
        None,
        user,
        application_id=str(application_id),
        page_context={"module_key": "style", "page_key": "style.center"},
        request_text="提取 204A231 款资料",
    )
    specialist_names = [name for name, item in registry.items() if item.get("kind") == "subsystem_specialist"]
    assert len(specialist_names) == 1
    specialist_name = specialist_names[0]
    assert registry[specialist_name]["current_page"] is True
    spec = next(item["function"] for item in tools if item["function"]["name"] == specialist_name)
    assert spec["strict"] is True
    assert "供应商" not in spec["description"]
    assert set(spec["parameters"]["properties"]) == {
        "instruction", "text_input", "context", "input_file_ids",
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
