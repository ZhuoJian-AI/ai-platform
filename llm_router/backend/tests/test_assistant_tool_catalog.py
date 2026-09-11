"""Pure tests for the provider-neutral Assistant Core tool catalog."""

from __future__ import annotations

import pytest

from app.services.assistant_tool_catalog import (
    entry_tool_definitions,
    partition_tool_specs,
    search_assistant_capabilities,
    search_business_capabilities,
    search_tool_specs,
)
from app.services.assistant_tool_protocol import descriptor_from_spec, tool_result


@pytest.fixture(autouse=True)
def db_engine():
    """Pure catalog tests do not require PostgreSQL."""

    yield


def _spec(name: str, description: str, **metadata):
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        **metadata,
    }


def test_descriptor_contains_the_complete_provider_neutral_contract():
    descriptor = descriptor_from_spec(
        _spec(
            "spreadsheet_create",
            "根据结构化数据创建 Excel 工作簿",
            output_schema={"type": "object"},
            risk_level="low",
            required_role_permissions=["workspace:create"],
            required_context="workspace",
            model_capability_binding=None,
            idempotency_policy="runId+toolCallId",
            confirmation_policy="none",
            artifact_policy="required",
        )
    )

    assert descriptor == {
        "name": "spreadsheet_create",
        "description": "根据结构化数据创建 Excel 工作簿",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "outputSchema": {"type": "object"},
        "riskLevel": "low",
        "requiredRolePermissions": ["workspace:create"],
        "requiredContext": "workspace",
        "modelCapabilityBinding": None,
        "idempotencyPolicy": "runId+toolCallId",
        "confirmationPolicy": "none",
        "artifactPolicy": "required",
    }


def test_partition_keeps_entry_and_current_page_tools_visible():
    search_entry = next(
        item["function"]
        for item in entry_tool_definitions()
        if item["function"]["name"] == "enterprise_capability_search"
    )
    specs = [
        {
            "name": search_entry["name"],
            "description": search_entry["description"],
            "input_schema": search_entry["parameters"],
        },
        _spec("order_update_owner", "修改订单负责人", required_context="current_page"),
        _spec("spreadsheet_create", "创建 Excel 工作簿"),
    ]

    visible, lazy = partition_tool_specs(specs, current_page_tool_names={"order_update_owner"})

    assert [item["name"] for item in visible] == [
        "enterprise_capability_search",
        "order_update_owner",
    ]
    assert [item["name"] for item in lazy] == ["spreadsheet_create"]


def test_chinese_capability_search_finds_the_relevant_small_tool_set():
    specs = [
        _spec("spreadsheet_create", "根据业务数据生成 Excel 表格"),
        _spec("speech_synthesize", "把文字合成为语音"),
        _spec("image_generation_tool", "根据文字生成图片"),
    ]

    selected = search_tool_specs("根据当前订单生成一份 Excel", specs, limit=2)

    assert selected
    assert selected[0]["name"] == "spreadsheet_create"
    assert len(selected) <= 2


def test_chinese_capability_search_can_activate_stable_audio_tools():
    specs = [
        _spec("audio_transcribe", "把录音转写成文字"),
        _spec("audio_understand", "直接理解音频并回答问题"),
        _spec("speech_synthesize", "把文字合成为语音文件"),
        _spec("spreadsheet_create", "生成 Excel 表格"),
    ]

    selected = search_tool_specs("把这段会议录音转写成文字", specs, limit=2)

    assert selected
    assert selected[0]["name"] == "audio_transcribe"
    assert all(item["name"] != "spreadsheet_create" for item in selected)


def test_enterprise_catalog_understands_business_language_without_system_names():
    candidates = [
        {
            "applicationName": "爱法贝生产协同",
            "moduleName": "款号资料中心",
            "pageName": "款号资料中心",
            "name": "查询款号图片资料",
            "description": "按款号查询款式图片和基础资料",
            "actionKey": "style_profile.query",
        },
        {
            "applicationName": "爱法贝生产协同",
            "moduleName": "工厂进度",
            "pageName": "工厂进度监测",
            "name": "查询延期订单",
            "description": "查看工厂延期风险",
            "actionKey": "factory_progress.query",
        },
    ]

    selected = search_business_capabilities("调用204A231款图片", candidates, limit=3)

    assert selected
    assert selected[0]["actionKey"] == "style_profile.query"


def test_tool_result_envelope_uses_one_typed_error_shape():
    result = tool_result(
        "retryable_error",
        error={
            "code": "invalid_tool_arguments",
            "messageZh": "订单号不能为空",
            "correctionFields": [{"field": "order_no", "reason": "必填"}],
            "retryable": True,
        },
    )

    assert result["status"] == "retryable_error"
    assert result["error"]["messageZh"] == "订单号不能为空"
    assert result["error"]["correctionFields"][0]["field"] == "order_no"


def test_business_candidates_cannot_crowd_out_matching_public_tool():
    result = search_assistant_capabilities(
        "把文字合成为语音文件",
        [_spec("speech_synthesize", "把文字合成为语音文件")],
        [{"name": "查询文件", "description": "查询业务文件记录", "actionKey": f"query_{i}"} for i in range(12)],
        limit=1,
    )
    assert result[0]["kind"] == "tool"
    assert result[0]["item"]["name"] == "speech_synthesize"


def test_business_operation_can_outrank_public_group_alias():
    result = search_assistant_capabilities(
        "查询款号图片资料",
        [_spec("image_generation_tool", "生成图片")],
        [{"name": "查询款号图片资料", "actionKey": "style.query"}],
        limit=1,
    )
    assert result[0]["kind"] == "business"


def test_merged_discovery_does_not_search_schema_or_activate_unrelated_tools():
    result = search_assistant_capabilities(
        "秘密工资",
        [_spec("speech_synthesize", "把文字合成为语音")],
        [{"name": "查询订单", "inputSchema": {"description": "秘密工资"}}],
    )
    assert result == []
