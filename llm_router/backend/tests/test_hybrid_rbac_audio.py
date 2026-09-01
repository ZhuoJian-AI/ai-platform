"""Contract regression tests for hybrid RBAC and MiMo audio phase one."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.llm_provider import LlmProviderCreate, ModelDeploymentCreate
from app.schemas.multimodal import VoiceCloneCreate, VoiceGrantInput
from app.schemas.user import UserCreate
from app.services.model_gateway import GatewayError, _test_wav_bytes, is_retryable_gateway_error
from app.services.scope_service import department_scope_ids, has_unrestricted_data_scope
from app.workers.multimodal_worker import _merge_transcripts, _pcm16_to_wav


def test_user_has_one_department_but_many_roles() -> None:
    department_id = uuid4()
    role_ids = [uuid4(), uuid4()]
    user = UserCreate(
        username="rbac-user",
        password="secure-pass",
        department_id=department_id,
        role_ids=role_ids,
    )
    assert user.department_id == department_id
    assert user.department_ids == [department_id]
    assert user.role_ids == role_ids

    with pytest.raises(ValidationError):
        UserCreate(
            username="invalid-user",
            password="secure-pass",
            department_ids=[department_id, uuid4()],
        )


def test_role_data_scope_expands_queries_without_changing_membership() -> None:
    primary = uuid4()
    delegated = uuid4()
    current_user = SimpleNamespace(
        department_id=str(primary),
        department_ids=(str(primary),),
        effective_data_scopes={
            "unrestricted": False,
            "own_only": False,
            "department_ids": (str(delegated),),
        },
    )
    assert set(department_scope_ids(current_user)) == {str(primary), str(delegated)}
    assert not has_unrestricted_data_scope(current_user)
    assert current_user.department_ids == (str(primary),)


def test_mimo_token_plan_is_rejected_and_audio_adapters_are_strict() -> None:
    with pytest.raises(ValidationError, match="Token Plan"):
        LlmProviderCreate(
            name="forbidden-token-plan",
            vendor="xiaomi_mimo",
            access_mode="payg",
            api_key="tp-do-not-use-in-saas",
        )

    provider = LlmProviderCreate(
        name="mimo-payg",
        vendor="xiaomi_mimo",
        access_mode="payg",
        api_key="sk-test",
    )
    assert provider.region == "cn"

    asr = ModelDeploymentCreate(
        model_id="mimo-v2.5-asr",
        adapter="openai_audio_transcription_chat",
        capabilities=["speech_to_text"],
    )
    assert asr.capabilities == ["speech_to_text"]
    with pytest.raises(ValidationError, match="transcription"):
        ModelDeploymentCreate(
            model_id="mimo-v2.5-asr",
            adapter="openai_audio_transcription_chat",
            capabilities=["chat"],
        )


def test_voice_clone_requires_explicit_confirmation_and_scoped_grants() -> None:
    payload = {
        "name": "authorized-clone",
        "sample_file_id": uuid4(),
        "evidence_file_id": uuid4(),
        "rights_holder": "权利人",
        "purpose": "企业内部播报",
        "valid_until": datetime.now(UTC) + timedelta(days=30),
        "confirmed": False,
    }
    with pytest.raises(ValidationError, match="explicit confirmation"):
        VoiceCloneCreate(**payload)

    with pytest.raises(ValidationError, match="scope_id"):
        VoiceGrantInput(scope_type="role")


def test_audio_helpers_produce_wav_and_remove_chunk_overlap() -> None:
    assert _merge_transcripts(
        ["这是第一段共同重复边界文本", "共同重复边界文本并继续第二段"],
    ) == "这是第一段共同重复边界文本并继续第二段"
    silence = _test_wav_bytes()
    assert silence[:4] == b"RIFF"
    assert silence[8:12] == b"WAVE"
    pcm_wav = _pcm16_to_wav(b"\x00\x00" * 240)
    assert pcm_wav[:4] == b"RIFF"
    assert pcm_wav[8:12] == b"WAVE"


def test_mimo_retry_policy_only_retries_transient_failures() -> None:
    assert is_retryable_gateway_error(GatewayError("quota_or_rate_limit"))
    assert is_retryable_gateway_error(GatewayError("provider_service_unavailable"))
    assert not is_retryable_gateway_error(GatewayError("invalid_credentials_or_permission"))
    assert not is_retryable_gateway_error(GatewayError("unsupported_audio_format"))
