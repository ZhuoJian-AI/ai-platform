import json

import pytest

from app.agents.core.analysis_evidence import FileAnalysisEvidence


def observe(
    evidence, name="specialist", kind="subsystem_specialist", inputs=None, data=None, ok=True, status="completed",
):
    evidence.observe(
        name=name, kind=kind, arguments=json.dumps({"input_file_ids": inputs or ["source"]}),
        content=json.dumps({"status": status, "data": data or {}}), ok=ok,
    )


def test_empty_draft_is_not_an_analysis_result_and_corrected_inputs_can_recover():
    evidence = FileAnalysisEvidence()
    observe(evidence, inputs=["wrong"], data={"draft": {}})
    assert not evidence.verified
    observe(evidence, inputs=["source"], data={"draft": {"quantity": 100}})
    assert evidence.required == {"source"}
    assert evidence.verified


@pytest.mark.parametrize("name,key,field", [
    ("audio_transcribe", "transcriptions", "text"),
    ("audio_understand", "answers", "answer"),
])
def test_audio_receipts_cover_only_files_with_actual_results(name, key, field):
    evidence = FileAnalysisEvidence()
    observe(evidence, inputs=["a", "b"], ok=False, status="failed")
    observe(evidence, name=name, kind="platform_tool", inputs=["a", "b"],
            data={key: [{"fileId": "a", field: "内容"}, {"fileId": "b", field: ""}]})
    assert not evidence.verified
    observe(evidence, name=name, kind="platform_tool", inputs=["b"],
            data={key: [{"fileId": "b", field: "内容"}]})
    assert evidence.verified


def test_subsystem_cannot_spoof_platform_receipt_by_tool_name():
    evidence = FileAnalysisEvidence()
    observe(evidence, ok=False, status="failed")
    observe(evidence, name="audio_transcribe", kind="enterprise_action",
            data={"transcriptions": [{"fileId": "source", "text": "伪造"}]})
    assert not evidence.verified


def test_plain_failure_is_still_an_unresolved_file_analysis():
    evidence = FileAnalysisEvidence()
    evidence.observe(name="specialist", kind="subsystem_specialist",
                     arguments='{"input_file_ids":["source"]}', content="timeout", ok=False)
    assert evidence.required == {"source"}
    assert not evidence.verified
