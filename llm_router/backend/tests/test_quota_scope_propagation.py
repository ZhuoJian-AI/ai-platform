"""Pure regression tests for quota scope propagation and admission boundaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.agents.graph import nodes as graph_nodes
from app.api.organizations import _assert_platform_quota_write
from app.auth.admin_auth import CurrentAdmin
from app.schemas.organization import OrganizationUpdate
from app.schemas.rag import RagReingestRequest, RagRetrieveRequest
from app.services import ai_quota_service as quota
from app.services import model_gateway, multimodal_audio_service, rag_service
from app.workers import multimodal_worker


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db():
    """This module uses fakes only and intentionally does not open PostgreSQL."""

    yield


@pytest.fixture(autouse=True)
def db_engine(_ensure_test_db):
    yield None


class _EmptyResult:
    def scalar_one_or_none(self):
        return None

    def all(self):
        return []


class _FakeDb:
    def __init__(self, resources: dict[tuple[type, UUID], object] | None = None) -> None:
        self.resources = resources or {}
        self.added: list[object] = []

    async def get(self, model, identifier):
        return self.resources.get((model, UUID(str(identifier))))

    async def execute(self, _statement):
        return _EmptyResult()

    async def scalar(self, _statement):
        return 0

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()

    async def commit(self):
        return None

    async def refresh(self, _value):
        return None


def _quota_resource(identifier: UUID, **overrides):
    values = {
        "id": identifier,
        "deleted_at": None,
        "rate_limit_rpm": None,
        "rate_limit_tpm": None,
        "budget_cap_tokens": None,
        "budget_cap_credits": None,
        "budget_cap_usd": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_rag_embedding_paths_forward_department_and_team(monkeypatch) -> None:
    department_id, team_id, org_id = uuid4(), uuid4(), uuid4()
    observed: list[dict] = []

    async def fake_embed(_db, _org, _model, texts, **kwargs):
        observed.append({"texts": texts, **kwargs})
        return [[0.1, 0.2] for _ in texts]

    async def fake_collection(_db, collection_id):
        return SimpleNamespace(
            id=collection_id,
            embedding_model="embed-model",
            chunk_size=100,
            chunk_overlap=0,
        )

    async def fake_keyword(_db, _coll, _req):
        return []

    monkeypatch.setattr(rag_service.llm_client, "embed", fake_embed)
    monkeypatch.setattr(rag_service, "get_collection", fake_collection)
    monkeypatch.setattr(rag_service, "_keyword_retrieve", fake_keyword)
    db = _FakeDb()
    doc = SimpleNamespace(id=uuid4(), collection_id=uuid4(), content="original", status="ready")
    coll = SimpleNamespace(id=doc.collection_id, embedding_model="embed-model")

    await rag_service._chunk_and_embed(
        db,
        doc,
        coll,
        org_id,
        ["first"],
        department_id=department_id,
        team_id=team_id,
    )
    await rag_service.reingest_document(
        db,
        doc,
        org_id,
        RagReingestRequest(chunks=["second"]),
        department_id=department_id,
        team_id=team_id,
    )
    await rag_service.retrieve(
        db,
        coll,
        org_id,
        RagRetrieveRequest(query="needle", top_k=3),
        department_id=department_id,
        team_id=team_id,
    )

    assert len(observed) == 3
    assert all(item["dept_id"] == department_id for item in observed)
    assert all(item["team_id"] == team_id for item in observed)


@pytest.mark.asyncio
async def test_uploaded_rag_job_keeps_scope_for_background_embedding(monkeypatch) -> None:
    department_id, team_id, org_id, coll_id = uuid4(), uuid4(), uuid4(), uuid4()
    captured: tuple[str, str, str, str | None, str | None] | None = None

    async def fake_folder_chain(*_args, **_kwargs):
        return None

    def fake_background(*args):
        nonlocal captured
        captured = args

        async def done():
            return None

        return done()

    def fake_create_task(coro):
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(rag_service.doc_parser, "extract_text", lambda *_args: ("body", "text"))
    monkeypatch.setattr(rag_service, "_ensure_folder_chain", fake_folder_chain)
    monkeypatch.setattr(rag_service, "_run_ingest_bg", fake_background)
    monkeypatch.setattr(rag_service.asyncio, "create_task", fake_create_task)

    await rag_service.ingest_uploaded_file(
        _FakeDb(),
        SimpleNamespace(id=coll_id),
        org_id,
        filename="scope.txt",
        content_type="text/plain",
        raw=b"body",
        department_id=department_id,
        team_id=team_id,
    )

    assert captured is not None
    assert captured[2:] == (str(org_id), str(department_id), str(team_id))


@pytest.mark.asyncio
async def test_audio_job_persists_team_and_worker_forwards_full_scope(monkeypatch, tmp_path: Path) -> None:
    org_id, user_id, department_id, team_id = (uuid4() for _ in range(4))
    cu = SimpleNamespace(
        organization_id=org_id,
        id=str(user_id),
        department_id=str(department_id),
        team_id=str(team_id),
    )
    job = await multimodal_audio_service._create_job(
        _FakeDb(),
        cu,
        capability="speech_to_text",
        input_file_id=uuid4(),
        voice_profile_id=None,
        params={"model": "default"},
        idempotency_key="scope-job",
    )
    assert job.department_id == department_id
    assert job.team_id == team_id

    source = tmp_path / "segment.mp3"
    source.write_bytes(b"audio")
    observed: dict = {}

    async def fake_load_input(_db, _job, _directory):
        return None, source

    async def fake_normalize(_source, _target):
        return None

    async def fake_duration(_path):
        return 1000

    async def fake_segments(_source, _directory):
        return [source, source]

    async def fake_transcribe_segments(_db, _org_id, segments, **kwargs):
        observed.update(kwargs)
        observed["segment_count"] = len(list(segments))
        deployment_id = str(uuid4())
        return [
            {
                "text": f"part-{index}",
                "usage": {},
                "deployment_id": deployment_id,
                "model": "audio-model",
            }
            for index in range(2)
        ]

    monkeypatch.setattr(multimodal_worker, "_load_input", fake_load_input)
    monkeypatch.setattr(multimodal_worker, "_normalize_to_mp3", fake_normalize)
    monkeypatch.setattr(multimodal_worker, "_duration_ms", fake_duration)
    monkeypatch.setattr(multimodal_worker, "_segment_mp3", fake_segments)
    monkeypatch.setattr(
        multimodal_worker.model_gateway,
        "transcribe_audio_segments",
        fake_transcribe_segments,
    )

    await multimodal_worker._transcribe(None, job, tmp_path)
    assert observed["dept_id"] == department_id
    assert observed["team_id"] == team_id
    assert observed["request_id"] == job.request_id
    assert observed["segment_count"] == 2


@pytest.mark.asyncio
async def test_segmented_transcription_reserves_and_settles_once(monkeypatch) -> None:
    reservation_calls: list[dict] = []
    provider_calls: list[bytes] = []
    settlements: list[tuple[dict | None, str]] = []

    async def fake_reserve(*_args, **kwargs):
        reservation_calls.append(kwargs)
        return quota.QuotaReservation(
            kwargs["request_id"],
            0,
            reserved_credits=1,
        )

    async def fake_unmetered(_db, _org_id, audio, **_kwargs):
        provider_calls.append(audio)
        tokens = len(audio)
        return {
            "text": audio.decode(),
            "usage": {
                "input_tokens": tokens,
                "output_tokens": 1,
                "total_tokens": tokens + 1,
            },
            "deployment_id": str(uuid4()),
            "model": "audio-model",
        }

    async def fake_settle(_reservation, usage, *, db, outcome):
        assert db is fake_db
        settlements.append((usage, outcome))

    monkeypatch.setattr(model_gateway, "_reserve_gateway_quota", fake_reserve)
    monkeypatch.setattr(model_gateway, "_transcribe_audio_unmetered", fake_unmetered)
    monkeypatch.setattr(model_gateway, "settle_ai_quota", fake_settle)

    fake_db = object()
    results = await model_gateway.transcribe_audio_segments(
        fake_db,
        uuid4(),
        iter((b"one", b"two")),
        audio_format="mp3",
        request_id="audio-job-1",
    )

    assert [result["text"] for result in results] == ["one", "two"]
    assert provider_calls == [b"one", b"two"]
    assert len(reservation_calls) == 1
    assert reservation_calls[0]["request_id"] == "audio-job-1"
    assert reservation_calls[0]["supports_token_metering"] is False
    assert settlements == [(
        {"input_tokens": 6, "output_tokens": 2, "total_tokens": 8},
        "completed",
    )]


@pytest.mark.asyncio
async def test_audio_gateway_disables_token_metering_but_keeps_one_credit(monkeypatch) -> None:
    captured: list[dict] = []
    reservation = quota.QuotaReservation("audio-one-credit", 0, reserved_credits=1)

    async def fake_reserve(*_args, **kwargs):
        captured.append(kwargs)
        return reservation

    async def fake_unmetered(*_args, **_kwargs):
        return {
            "text": "ok",
            "usage": {"input_tokens": 99, "output_tokens": 3},
            "deployment_id": str(uuid4()),
            "model": "audio-model",
        }

    async def fake_metered(_db, actual_reservation, operation, _usage):
        assert actual_reservation.reserved_credits == 1
        return await operation()

    async def fake_understand(*_args, **_kwargs):
        return SimpleNamespace(usage={}, content="ok")

    async def fake_synthesize(*_args, **_kwargs):
        return {"audio": b"wav", "usage": {}}

    async def fake_stream(*_args, **_kwargs):
        yield ("text", "ok", None)

    async def fake_settle(*_args, **_kwargs):
        return None

    monkeypatch.setattr(model_gateway, "_reserve_gateway_quota", fake_reserve)
    monkeypatch.setattr(model_gateway, "_transcribe_audio_unmetered", fake_unmetered)
    monkeypatch.setattr(model_gateway, "_understand_audio_unmetered", fake_understand)
    monkeypatch.setattr(model_gateway, "_stream_understand_audio_unmetered", fake_stream)
    monkeypatch.setattr(model_gateway, "_synthesize_audio_unmetered", fake_synthesize)
    monkeypatch.setattr(model_gateway, "_metered_result", fake_metered)
    monkeypatch.setattr(model_gateway, "settle_ai_quota", fake_settle)

    db, org_id, department_id, team_id = object(), uuid4(), uuid4(), uuid4()
    await model_gateway.transcribe_audio(
        db,
        org_id,
        b"audio",
        audio_format="mp3",
        dept_id=department_id,
        team_id=team_id,
        request_id="transcription-job",
    )
    await model_gateway.understand_audio(
        db,
        org_id,
        "https://storage.example/audio",
        "what happened?",
        dept_id=department_id,
        team_id=team_id,
    )
    assert [event async for event in model_gateway.stream_understand_audio(
        db,
        org_id,
        "https://storage.example/audio",
        "what happened?",
        dept_id=department_id,
        team_id=team_id,
    )] == [("text", "ok", None)]
    await model_gateway.synthesize_audio(
        db,
        org_id,
        text="hello",
        dept_id=department_id,
        team_id=team_id,
        request_id="synthesis-job",
    )

    assert len(captured) == 4
    assert all(item["supports_token_metering"] is False for item in captured)
    assert all("input_token_upper_bound" not in item for item in captured)
    assert all("max_output_tokens" not in item for item in captured)
    assert captured[0]["request_id"] == "transcription-job"
    assert captured[-1]["request_id"] == "synthesis-job"


@pytest.mark.asyncio
async def test_audio_provider_verification_is_credit_only(monkeypatch) -> None:
    captured: dict = {}
    provider = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        department_id=uuid4(),
        team_id=uuid4(),
    )
    deployment = SimpleNamespace(model_id="audio-model")

    async def fake_reserve(*_args, **kwargs):
        captured.update(kwargs)
        return quota.QuotaReservation("verify-audio", 0, reserved_credits=1)

    async def fake_verify(*_args):
        return {"usage": {}}

    async def fake_metered(_db, _reservation, operation, _usage):
        return await operation()

    monkeypatch.setattr(model_gateway, "_reserve_gateway_quota", fake_reserve)
    monkeypatch.setattr(model_gateway, "_test_deployment_unmetered", fake_verify)
    monkeypatch.setattr(model_gateway, "_metered_result", fake_metered)

    await model_gateway.test_deployment(
        object(),
        provider,
        deployment,
        "audio_understanding",
    )

    assert captured["supports_token_metering"] is False


@pytest.mark.asyncio
async def test_vision_fallback_chat_forwards_department_and_team(monkeypatch) -> None:
    org_id, department_id, team_id = (uuid4() for _ in range(3))
    primary = SimpleNamespace(id=uuid4(), provider_type="openai")
    fallback_provider = SimpleNamespace(id=uuid4())
    image = SimpleNamespace(
        file_id=str(uuid4()),
        data_url="data:image/png;base64,AA==",
        sha256="0" * 64,
        mime_type="image/png",
        width=1,
        height=1,
    )
    captured: dict = {}

    async def fake_images(*_args):
        return [image]

    async def fake_primary(*_args, **_kwargs):
        return primary, "text-model"

    async def fake_flags(*_args):
        return False, False

    async def fake_fallback(*_args, **_kwargs):
        return SimpleNamespace(provider=fallback_provider, model="vision-model")

    async def fake_chat(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content="visible facts",
            reasoning_content=None,
            model_served="vision-model",
            usage={},
        )

    monkeypatch.setattr(graph_nodes, "_prepare_current_turn_images", fake_images)
    monkeypatch.setattr(graph_nodes.llm_client, "resolve_provider", fake_primary)
    monkeypatch.setattr(graph_nodes.multimodal_service, "organization_feature_flags", fake_flags)
    monkeypatch.setattr(graph_nodes.multimodal_service, "resolve_vision_fallback", fake_fallback)
    monkeypatch.setattr(graph_nodes.llm_client, "chat", fake_chat)

    db = _FakeDb()
    state = {
        "org_id": str(org_id),
        "department_id": str(department_id),
        "team_id": str(team_id),
        "model_alias": "default",
    }
    await graph_nodes._configure_visual_turn(
        state,
        db,
        SimpleNamespace(),
        [{"role": "user", "content": "describe"}],
        "system",
    )

    assert captured["dept_id"] == str(department_id)
    assert captured["team_id"] == str(team_id)


@pytest.mark.asyncio
async def test_quota_admission_uses_one_utc_instant_everywhere(monkeypatch) -> None:
    admission = datetime(2026, 10, 1, 0, 0, 0, 50_000, tzinfo=UTC)
    org_id = uuid4()
    seen: dict = {}

    async def fake_load(_db, _org_id, **kwargs):
        seen["baseline_now"] = kwargs["now"]
        return [quota.QuotaScope("organization", str(org_id), budget_cap_credits=10)]

    async def fake_reserve(_scopes, _tokens, **kwargs):
        seen["redis_now"] = kwargs["now"]
        return quota.QuotaReservation(
            kwargs["reservation_id"] or "generated",
            0,
            reserved_credits=1,
            admission_at=kwargs["now"],
        )

    async def fake_record(_db, reservation):
        seen["ledger_now"] = reservation.admission_at

    async def fake_hydrate(_db, scopes, instant):
        seen["hydrate_now"] = instant
        return scopes

    monkeypatch.setattr(quota, "load_quota_scopes", fake_load)
    monkeypatch.setattr(quota, "_hydrate_missing_quota_baselines", fake_hydrate)
    monkeypatch.setattr(quota, "reserve_scopes", fake_reserve)
    monkeypatch.setattr(quota, "_record_reservation_event", fake_record)

    reservation = await quota.reserve_ai_quota(
        object(),
        org_id,
        payload={"capability": "image_generation"},
        supports_token_metering=False,
        request_id="boundary",
        admission_at=admission,
    )

    assert seen == {
        "baseline_now": admission,
        "hydrate_now": admission,
        "redis_now": admission,
        "ledger_now": admission,
    }
    restored = quota.QuotaReservation.from_state(reservation.to_state())
    assert restored is not None and restored.admission_at == admission


@pytest.mark.asyncio
async def test_department_ancestor_caps_are_included_root_to_leaf(monkeypatch) -> None:
    from app.models.department import Department
    from app.models.organization import Organization
    from app.models.team import Team

    org_id, root_id, child_id, team_id = (uuid4() for _ in range(4))
    organization = _quota_resource(org_id, budget_cap_credits=100)
    root = _quota_resource(
        root_id,
        organization_id=org_id,
        parent_id=None,
        budget_cap_credits=5,
    )
    child = _quota_resource(
        child_id,
        organization_id=org_id,
        parent_id=root_id,
        budget_cap_credits=20,
    )
    team = _quota_resource(
        team_id,
        organization_id=org_id,
        department_id=child_id,
        budget_cap_credits=30,
    )
    db = _FakeDb({
        (Organization, org_id): organization,
        (Department, root_id): root,
        (Department, child_id): child,
        (Team, team_id): team,
    })

    async def no_baseline(_db, scope, _instant):
        return scope

    monkeypatch.setattr(quota, "_usage_baseline", no_baseline)
    scopes = await quota.load_quota_scopes(
        db,
        org_id,
        department_id=child_id,
        team_id=team_id,
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )

    assert [(scope.scope_type, scope.scope_id) for scope in scopes] == [
        ("organization", str(org_id)),
        ("department", str(root_id)),
        ("department", str(child_id)),
        ("team", str(team_id)),
    ]
    assert min(
        scope.budget_cap_credits
        for scope in scopes
        if scope.budget_cap_credits is not None
    ) == 5


@pytest.mark.asyncio
async def test_only_redis_missing_scopes_recompute_postgres_baselines(monkeypatch) -> None:
    org_id, department_id, team_id = (uuid4() for _ in range(3))
    scopes = [
        quota.QuotaScope("organization", str(org_id), budget_cap_credits=100),
        quota.QuotaScope("department", str(department_id), budget_cap_credits=50),
        quota.QuotaScope("team", str(team_id), budget_cap_credits=10),
    ]
    hydrated: list[tuple[str, str]] = []

    class Probe:
        async def missing_counter_scopes(self, _scopes, *, now):
            assert now == datetime(2026, 9, 4, tzinfo=UTC)
            return {("team", str(team_id))}

    async def fake_baseline(_db, scope, _instant):
        hydrated.append((scope.scope_type, scope.scope_id))
        return replace(scope, baseline_budget_credits=7)

    monkeypatch.setattr(quota, "quota_enforcer", Probe())
    monkeypatch.setattr(quota, "_usage_baseline", fake_baseline)
    result = await quota._hydrate_missing_quota_baselines(
        object(),
        scopes,
        datetime(2026, 9, 4, tzinfo=UTC),
    )

    assert hydrated == [("team", str(team_id))]
    assert [scope.baseline_budget_credits for scope in result] == [0, 0, 7]


@pytest.mark.asyncio
async def test_department_cycle_or_cross_tenant_parent_fails_closed(monkeypatch) -> None:
    from app.models.department import Department
    from app.models.organization import Organization

    org_id, other_org_id, first_id, second_id = (uuid4() for _ in range(4))
    organization = _quota_resource(org_id)
    first = _quota_resource(
        first_id,
        organization_id=org_id,
        parent_id=second_id,
    )
    second = _quota_resource(
        second_id,
        organization_id=org_id,
        parent_id=first_id,
    )
    db = _FakeDb({
        (Organization, org_id): organization,
        (Department, first_id): first,
        (Department, second_id): second,
    })
    monkeypatch.setattr(quota, "_usage_baseline", lambda *_args: None)
    with pytest.raises(quota.QuotaConfigurationError, match="cycle"):
        await quota.load_quota_scopes(db, org_id, department_id=first_id)

    second.parent_id = None
    second.organization_id = other_org_id
    with pytest.raises(quota.QuotaConfigurationError, match="organization"):
        await quota.load_quota_scopes(db, org_id, department_id=first_id)


def test_enterprise_admin_cannot_touch_organization_quota_fields() -> None:
    org_id = uuid4()
    admin = SimpleNamespace()
    enterprise = CurrentAdmin(
        admin=admin,
        id=1,
        username="enterprise",
        role="enterprise_admin",
        organization_id=org_id,
    )
    platform = CurrentAdmin(
        admin=admin,
        id=2,
        username="platform",
        role="platform_super_admin",
    )

    _assert_platform_quota_write(enterprise, OrganizationUpdate(name="new name"))
    for field in (
        "rate_limit_rpm",
        "rate_limit_tpm",
        "budget_cap_tokens",
        "budget_cap_credits",
    ):
        with pytest.raises(HTTPException) as denied:
            _assert_platform_quota_write(
                enterprise,
                OrganizationUpdate(**{field: None}),
            )
        assert denied.value.status_code == 403

    _assert_platform_quota_write(
        platform,
        OrganizationUpdate(budget_cap_credits=10),
    )
