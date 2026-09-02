"""Organization feature gates must survive a mutable slug rename."""

from uuid import uuid4

import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("method_name", "enabled_field", "allowlist_field"),
    [
        ("agent_skills_enabled_for", "code_skills_enabled", "agent_skills_org_allowlist"),
        (
            "multimodal_vision_enabled_for",
            "multimodal_vision_enabled",
            "multimodal_vision_org_allowlist",
        ),
        (
            "image_generation_enabled_for",
            "image_generation_enabled",
            "image_generation_org_allowlist",
        ),
        ("model_gateway_enabled_for", "model_gateway_enabled", "model_gateway_org_allowlist"),
        (
            "multimodal_audio_enabled_for",
            "multimodal_audio_enabled",
            "multimodal_audio_org_allowlist",
        ),
    ],
)
def test_org_feature_gate_accepts_stable_id_and_slug_fallback(
    method_name: str,
    enabled_field: str,
    allowlist_field: str,
):
    organization_id = uuid4()
    foreign_id = uuid4()
    configured = Settings(
        _env_file=None,
        **{
            enabled_field: True,
            allowlist_field: f"legacy-slug,{organization_id}",
        },
    )
    enabled_for = getattr(configured, method_name)

    assert enabled_for("legacy-slug", organization_id=foreign_id) is True
    assert enabled_for("alphabet", organization_id=organization_id) is True
    assert enabled_for("renamed-again", organization_id=organization_id) is True
    assert enabled_for("alphabet", organization_id=foreign_id) is False


@pytest.mark.parametrize(
    ("method_name", "enabled_field", "allowlist_field"),
    [
        ("agent_skills_enabled_for", "code_skills_enabled", "agent_skills_org_allowlist"),
        (
            "multimodal_vision_enabled_for",
            "multimodal_vision_enabled",
            "multimodal_vision_org_allowlist",
        ),
        (
            "image_generation_enabled_for",
            "image_generation_enabled",
            "image_generation_org_allowlist",
        ),
        ("model_gateway_enabled_for", "model_gateway_enabled", "model_gateway_org_allowlist"),
        (
            "multimodal_audio_enabled_for",
            "multimodal_audio_enabled",
            "multimodal_audio_org_allowlist",
        ),
    ],
)
def test_org_feature_gate_still_honors_global_switch(
    method_name: str,
    enabled_field: str,
    allowlist_field: str,
):
    configured = Settings(
        _env_file=None,
        **{enabled_field: False, allowlist_field: "alphabet"},
    )

    assert getattr(configured, method_name)("alphabet", organization_id=uuid4()) is False
