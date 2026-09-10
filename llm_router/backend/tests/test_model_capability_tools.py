from __future__ import annotations

import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from app.agents.graph import model_capability_tools as capability_tools


@pytest.fixture(autouse=True)
def db_engine():
    """Tool unit tests use explicit service doubles, not PostgreSQL."""
    yield


class _Db:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


def _user(*permissions: str):
    return SimpleNamespace(
        organization_id=uuid4(),
        department_id=str(uuid4()),
        permission_codes=permissions,
        id=str(uuid4()),
    )


def _open_result(value: str) -> dict:
    result = json.loads(value)
    assert isinstance(result, dict)
    return result


@pytest.mark.asyncio
async def test_capability_availability_uses_default_route_and_role_permissions(monkeypatch):
    user = _user(
        "multimodal.audio.transcribe",
        "multimodal.audio.understand",
        "multimodal.speech.use",
    )
    requested: list[tuple[str, str]] = []

    async def fake_vision(*_args, **_kwargs):
        return object()

    async def fake_enabled(*_args, **_kwargs):
        return None

    async def fake_resolve(_db, _org_id, model_alias, capability, **_kwargs):
        requested.append((model_alias, capability))
        return object() if capability != "voice_clone" else None

    monkeypatch.setattr(capability_tools.multimodal_service, "resolve_vision_fallback", fake_vision)
    monkeypatch.setattr(capability_tools.multimodal_audio_service, "require_multimodal_enabled", fake_enabled)
    monkeypatch.setattr(capability_tools.model_gateway, "resolve_deployment", fake_resolve)

    availability = await capability_tools.model_capability_availability(object(), user)

    assert availability == {
        "vision": True,
        "audio_transcribe": True,
        "audio_understand": True,
        "speech_synthesize": True,
        "speech_modes": ["standard", "design"],
    }
    assert requested
    assert {model_alias for model_alias, _ in requested} == {"default"}


def test_model_capability_schemas_do_not_expose_provider_configuration():
    tools = capability_tools.model_capability_tool_definitions(
        {
            "audio_transcribe": True,
            "audio_understand": True,
            "speech_synthesize": True,
            "speech_modes": ["standard", "design", "clone"],
        }
    )
    encoded = json.dumps(tools).lower()
    assert {item["function"]["name"] for item in tools} == {
        "audio_transcribe",
        "audio_understand",
        "speech_synthesize",
    }
    for forbidden in ("api_key", "base_url", "provider_name", "model_id", "endpoint_url"):
        assert forbidden not in encoded
    assert all(item["function"]["strict"] is True for item in tools)
    assert all(
        item["function"]["parameters"]["additionalProperties"] is False
        for item in tools
    )


@pytest.mark.asyncio
async def test_audio_transcribe_rechecks_file_and_uses_default_capability_route(monkeypatch):
    principal = _user("multimodal.audio.transcribe")
    file = SimpleNamespace(id=uuid4(), path="录音/会议.wav")
    called: dict = {}

    async def authorize(value, current):
        called["authorized"] = (value, current)
        return file, principal

    async def load_file_bytes(_file):
        return b"RIFF\x00\x00\x00\x00WAVEpayload"

    async def check_permission(*_args, **_kwargs):
        return None

    async def transcribe(_db, _org_id, raw, **kwargs):
        called["transcribe"] = (raw, kwargs)
        return {"text": "会议决定明天交付", "segments": [{"start": 0, "end": 2}]}

    monkeypatch.setattr(capability_tools.workspace_service, "load_file_bytes", load_file_bytes)
    monkeypatch.setattr(capability_tools, "_check_audio_permission", check_permission)
    monkeypatch.setattr(capability_tools.model_gateway, "transcribe_audio", transcribe)

    result = _open_result(
        await capability_tools.execute_audio_tool(
            db=object(),
            state={"org_id": str(principal.organization_id), "run_id": "run-1"},
            name="audio_transcribe",
            params={"input_file_ids": [str(file.id)]},
            user=principal,
            authorize_input=authorize,
            resolve_output_workspace=None,
            task_source=None,
            file_identity=None,
        )
    )

    assert result["status"] == "completed"
    assert result["data"]["transcriptions"][0]["text"] == "会议决定明天交付"
    assert called["transcribe"][1]["model_alias"] == "default"


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", [None, "workspace", "speech", "target"])
async def test_speech_synthesize_commits_only_with_current_permissions(monkeypatch, revocation):
    db = _Db()
    principal = _user("multimodal.speech.use")
    workspace = SimpleNamespace(id=uuid4(), name="zhangsan")
    file_id = uuid4()
    version_id = uuid4()
    saved = SimpleNamespace(
        id=file_id,
        path="平台工具输出/task/voice.mp3",
        metadata_={},
        content_hash="a" * 64,
        current_version_id=version_id,
    )
    called: dict = {}

    resolve_calls = 0
    permission_calls = 0

    async def resolve_output(_params, _user):
        nonlocal resolve_calls
        resolve_calls += 1
        if resolve_calls == 2 and revocation == "workspace":
            return None, principal, "工作空间权限已撤销"
        if resolve_calls == 2 and revocation == "target":
            return SimpleNamespace(id=uuid4()), principal, None
        return workspace, principal, None

    async def check_permission(*_args, **_kwargs):
        nonlocal permission_calls
        permission_calls += 1
        if permission_calls == 2 and revocation == "speech":
            return "当前角色语音权限已撤销"
        return None

    async def scan(*_args, **_kwargs):
        return SimpleNamespace(blocked=False, redacted_text=None)

    async def synthesize(_db, _org_id, **kwargs):
        called["synthesize"] = kwargs
        return {
            "audio": b"ID3\x04\x00\x00\x00\x00\x00\x00payload",
            "format": "mp3",
            "model": "mimo-v2.5-tts",
            "usage": {},
        }

    async def ingest(*_args, **kwargs):
        called["ingest"] = kwargs
        return saved

    async def sync(*_args, **_kwargs):
        return None

    async def task_source():
        return {"created_by_user_id": principal.id}

    async def file_identity(_db, _file, _workspace, _principal):
        return {
            "file_id": str(file_id),
            "version_id": str(version_id),
            "workspace_id": str(workspace.id),
            "canonical_path": "zhangsan:/voice.mp3",
        }

    monkeypatch.setattr(capability_tools, "_check_audio_permission", check_permission)
    monkeypatch.setattr(capability_tools, "scan_request", scan)
    monkeypatch.setattr(capability_tools.model_gateway, "synthesize_audio", synthesize)
    monkeypatch.setattr(capability_tools.workspace_service, "ingest_uploaded_file", ingest)
    monkeypatch.setattr(capability_tools.workspace_service, "sync_current_version", sync)

    result = _open_result(
        await capability_tools.execute_audio_tool(
            db=db,
            state={"org_id": str(principal.organization_id), "run_id": "run-2", "task_id": "task-2"},
            name="speech_synthesize",
            params={
                "text": "请播报今日生产进度",
                "output_format": "mp3",
                "output_name": "生产播报.mp3",
                "_tool_call_id": "call-2",
            },
            user=principal,
            authorize_input=None,
            resolve_output_workspace=resolve_output,
            task_source=task_source,
            file_identity=file_identity,
        )
    )

    assert resolve_calls == 2
    if revocation:
        assert result["status"] == "failed"
        assert not result.get("artifacts")
        assert "ingest" not in called
        assert not db.added
        assert result["error"]["code"] == (
            "speech_permission_changed" if revocation == "speech" else "workspace_permission_changed"
        )
        return
    assert permission_calls == 2
    assert result["status"] == "completed"
    assert result["artifacts"][0]["file_id"] == str(file_id)
    assert result["artifacts"][0]["version_id"] == str(version_id)
    assert called["synthesize"]["model_alias"] == "default"
    assert called["ingest"]["content_type"] == "audio/mpeg"
    assert called["ingest"]["created_by_user_id"] == principal.id
    assert db.added
    audit = next(item for item in db.added if hasattr(item, "model_requested"))
    assert audit.model_requested == "default:text_to_speech"


@pytest.mark.asyncio
async def test_image_understand_uses_verified_vision_route(monkeypatch):
    principal = _user()
    file = SimpleNamespace(
        id=uuid4(),
        path="款号/204A231.png",
        metadata_={"mime": "image/png", "name": "204A231.png"},
    )
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buffer, format="PNG")
    png = buffer.getvalue()
    called: dict = {}

    async def authorize(_value, _user):
        return file, principal

    async def load_file_bytes(_file):
        return png

    async def scan(*_args, **_kwargs):
        return SimpleNamespace(blocked=False, redacted_text=None)

    async def resolve(*_args, **_kwargs):
        return SimpleNamespace(provider=object(), model="mimo-v2.5-pro")

    async def chat(_db, _org_id, model_alias, _messages, **kwargs):
        called["chat"] = (model_alias, kwargs)
        return SimpleNamespace(content="这是一张服装款式图", reasoning_content=None)

    monkeypatch.setattr(capability_tools.workspace_service, "load_file_bytes", load_file_bytes)
    monkeypatch.setattr(capability_tools, "scan_request", scan)
    monkeypatch.setattr(capability_tools.multimodal_service, "resolve_vision_fallback", resolve)
    monkeypatch.setattr(capability_tools.model_gateway, "chat", chat)

    result = _open_result(
        await capability_tools.execute_image_understanding(
            db=object(),
            state={"org_id": str(principal.organization_id)},
            params={"input_file_ids": [str(file.id)], "question": "这是什么款式？"},
            user=principal,
            authorize_input=authorize,
        )
    )

    assert result["status"] == "completed"
    assert result["data"]["answer"] == "这是一张服装款式图"
    assert called["chat"][0] == "mimo-v2.5-pro"
    assert called["chat"][1]["provider_override"] is not None
