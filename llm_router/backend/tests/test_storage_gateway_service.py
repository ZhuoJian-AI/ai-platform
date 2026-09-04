from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models.workspace import OfficeSaveEvent
from app.services import storage_gateway_service as storage
from app.services import workspace_office_edit_service as office_edit
from app.services import workspace_service


@asynccontextmanager
async def _noop_savepoint():
    yield


@pytest.fixture(autouse=True)
def db_engine():
    """Pure service tests do not need the PostgreSQL autouse fixture."""
    yield


def _configure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "storage_gateway_url", "https://storage.example.test")
    monkeypatch.setattr(settings, "storage_project_token", "project-token")
    monkeypatch.setattr(settings, "storage_public_endpoint", "https://oss-cn-hongkong.aliyuncs.com")
    monkeypatch.setattr(settings, "storage_internal_endpoint", "https://oss-cn-hongkong-internal.aliyuncs.com")
    monkeypatch.setattr(settings, "storage_accelerate_endpoint", "https://oss-accelerate.aliyuncs.com")


def _configure_office_edit(monkeypatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "workspace_object_storage_enabled", True)
    monkeypatch.setattr(settings, "workspace_weboffice_edit_enabled", True)
    monkeypatch.setattr(settings, "workspace_office_event_callback_secret", "c" * 32)


async def _async_true() -> bool:
    return True


def test_office_save_source_user_id_accepts_uuid_length():
    assert OfficeSaveEvent.__table__.c.source_user_id.type.length >= 64


def test_internal_endpoint_rewrite_preserves_bucket_and_query(monkeypatch):
    _configure(monkeypatch)
    rewritten = storage._internal_signed_url(
        "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/1/assets/a.xlsx?Expires=1&Signature=x"
    )
    assert rewritten == (
        "https://bucket.oss-cn-hongkong-internal.aliyuncs.com/"
        "projects/1/assets/a.xlsx?Expires=1&Signature=x"
    )


@pytest.mark.asyncio
async def test_upload_and_download_use_scoped_signed_urls(monkeypatch):
    _configure(monkeypatch)
    calls: list[tuple[str, str]] = []

    class FakeResponse:
        def __init__(self, payload=None, content=b""):
            self._payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            calls.append(("POST", url))
            assert kwargs["headers"]["Authorization"] == "Bearer project-token"
            if url.endswith("/v1/uploads/sign"):
                assert kwargs["json"]["content_hash"] == hashlib.sha256(b"original").hexdigest()
                return FakeResponse({
                    "object_key": "projects/7/assets/report.xlsx",
                    "url": "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/7/assets/report.xlsx?sig=1",
                    "headers": {
                        "Content-Type": "application/test",
                        "x-oss-meta-content-sha256": hashlib.sha256(b"original").hexdigest(),
                    },
                })
            return FakeResponse({
                "object_key": kwargs["json"]["object_key"],
                "url": "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/7/assets/report.xlsx?sig=2",
            })

        async def put(self, url, **kwargs):
            calls.append(("PUT", url))
            assert "oss-cn-hongkong-internal" in url
            assert kwargs["content"] == b"original"
            assert kwargs["headers"]["x-oss-meta-content-sha256"] == hashlib.sha256(
                b"original"
            ).hexdigest()
            return FakeResponse()

        async def get(self, url):
            calls.append(("GET", url))
            assert "oss-cn-hongkong-internal" in url
            return FakeResponse(content=b"original")

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    ref = await storage.upload_bytes(b"original", filename="report.xlsx", content_type="application/test")
    assert ref == "oss://projects/7/assets/report.xlsx"
    assert await storage.download_bytes(ref) == b"original"
    assert [method for method, _ in calls] == ["POST", "PUT", "POST", "GET"]


def _save_event(*, imm_version: str = "", event_time: str = "") -> SimpleNamespace:
    return SimpleNamespace(imm_version=imm_version, event_time=event_time)


def test_office_save_order_prefers_comparable_numeric_imm_version():
    assert office_edit._save_event_order(
        _save_event(imm_version="11", event_time="2026-09-03T10:00:00Z"),
        _save_event(imm_version="10", event_time="2026-09-03T11:00:00Z"),
    ) == 1
    assert office_edit._save_event_order(
        _save_event(imm_version="9"), _save_event(imm_version="10"),
    ) == -1


def test_office_save_order_uses_timestamp_only_when_versions_are_not_comparable():
    assert office_edit._save_event_order(
        _save_event(event_time="2026-09-03T11:00:00Z"),
        _save_event(event_time="2026-09-03T10:00:00Z"),
    ) == 1
    assert office_edit._save_event_order(
        _save_event(imm_version="opaque"), _save_event(imm_version="also-opaque"),
    ) is None


@pytest.mark.asyncio
async def test_closed_office_room_remains_callback_provenance(monkeypatch):
    """A delayed save can match an exact recent room after its 5m active grace."""
    file_id = "c52e1167-f8de-4e03-bfef-9e3045cf8c60"
    room = SimpleNamespace(
        id="22f1af6b-4d98-42d2-bd44-b7347be292a3",
        workspace_file_id=file_id,
        source_content_ref="oss://projects/repo/collab/source.xlsx",
        actor_type="user",
        actor_id="user-1",
        source_revision="b" * 64,
        created_at=datetime.now(UTC) - timedelta(hours=2),
        closed_at=datetime.now(UTC) - timedelta(hours=1),
    )
    statements = []

    class Result:
        def __init__(self, *, scalar=None, rows=None):
            self.scalar = scalar
            self.rows = rows or []

        def scalar_one_or_none(self):
            return self.scalar

        def scalars(self):
            return self.rows

    class FakeDb:
        def __init__(self):
            self.added = []

        async def execute(self, statement):
            statements.append(statement)
            return Result(scalar=None)

        async def get(self, _model, requested_id):
            assert str(requested_id) == room.id
            return room

        def add(self, row):
            self.added.append(row)

        async def flush(self):
            return None

        def begin_nested(self):
            return _noop_savepoint()

    async def fake_get_file(_db, requested_id):
        assert str(requested_id) == file_id
        return SimpleNamespace(id=requested_id)

    monkeypatch.setattr(workspace_service, "get_file", fake_get_file)
    event = await office_edit.record_save_event(FakeDb(), {
        "event_id": "e" * 64,
        "file_id": file_id,
        "room_id": room.id,
        "repository_id": "repo",
        "source_object_key": "projects/repo/collab/source.xlsx",
        "object_key": "projects/repo/assets/saved.xlsx",
        "version_id": None,
        "etag": "etag-1",
        "size": 10,
        "content_type": "application/octet-stream",
        "content_hash": "a" * 64,
        "user_id": office_edit.weboffice_user_id("user", "user-1"),
        "source_revision": "b" * 64,
        "integrity_algorithm": "crc64ecma",
        "integrity_value": "12345",
        "imm_version": "12",
        "event_time": "2026-09-03T10:00:00Z",
    })
    assert str(event.office_edit_room_id) == room.id
    assert event.notified_storage_version_id is None


@pytest.mark.asyncio
async def test_refreshed_active_room_older_than_24h_remains_callback_provenance(monkeypatch):
    file_id = "c52e1167-f8de-4e03-bfef-9e3045cf8c60"
    room = SimpleNamespace(
        id="22f1af6b-4d98-42d2-bd44-b7347be292a3",
        workspace_file_id=file_id,
        source_content_ref="oss://projects/repo/collab/source.xlsx",
        actor_type="user",
        actor_id="user-1",
        source_revision="b" * 64,
        status="open",
        created_at=datetime.now(UTC) - timedelta(days=2),
        closed_at=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )

    class Result:
        def scalar_one_or_none(self):
            return None

    class FakeDb:
        async def execute(self, _statement):
            return Result()

        async def get(self, _model, _requested_id):
            return room

        def add(self, _row):
            return None

        async def flush(self):
            return None

        def begin_nested(self):
            return _noop_savepoint()

    async def fake_get_file(_db, requested_id):
        return SimpleNamespace(id=requested_id)

    monkeypatch.setattr(workspace_service, "get_file", fake_get_file)
    event = await office_edit.record_save_event(FakeDb(), {
        "event_id": "f" * 64, "file_id": file_id, "room_id": room.id,
        "repository_id": "repo",
        "source_object_key": "projects/repo/collab/source.xlsx",
        "object_key": "projects/repo/assets/saved-2.xlsx", "version_id": None,
        "etag": "etag-2", "size": 11, "content_type": "application/octet-stream",
        "content_hash": "a" * 64,
        "user_id": office_edit.weboffice_user_id("user", "user-1"),
        "source_revision": "b" * 64,
        "integrity_algorithm": "crc64ecma", "integrity_value": "23456",
    })
    assert str(event.office_edit_room_id) == room.id


@pytest.mark.asyncio
async def test_duplicate_save_callback_insert_race_returns_unique_winner(monkeypatch):
    file_id = "c52e1167-f8de-4e03-bfef-9e3045cf8c60"
    room_id = "22f1af6b-4d98-42d2-bd44-b7347be292a3"
    room = SimpleNamespace(
        id=room_id, workspace_file_id=file_id,
        source_content_ref="oss://projects/repo/collab/source.xlsx",
        actor_type="user", actor_id="user-1", source_revision="b" * 64,
        status="open", created_at=datetime.now(UTC), closed_at=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    winner = SimpleNamespace(gateway_event_id="e" * 64)

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class FakeDb:
        def __init__(self):
            self.results = iter((None, winner))

        async def execute(self, _statement):
            return Result(next(self.results))

        async def get(self, _model, _requested_id):
            return room

        def add(self, _row):
            return None

        def begin_nested(self):
            return _noop_savepoint()

        async def flush(self):
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    async def fake_get_file(_db, requested_id):
        return SimpleNamespace(id=requested_id)

    monkeypatch.setattr(workspace_service, "get_file", fake_get_file)
    saved = await office_edit.record_save_event(FakeDb(), {
        "event_id": "e" * 64, "file_id": file_id, "room_id": room_id,
        "repository_id": "repo",
        "source_object_key": "projects/repo/collab/source.xlsx",
        "object_key": "projects/repo/assets/saved.xlsx", "version_id": None,
        "etag": "etag", "size": 10, "content_type": "application/octet-stream",
        "content_hash": "a" * 64,
        "user_id": office_edit.weboffice_user_id("user", "user-1"),
        "source_revision": "b" * 64,
        "integrity_algorithm": "crc64ecma", "integrity_value": "12345",
    })
    assert saved is winner


@pytest.mark.asyncio
async def test_save_event_room_id_cannot_be_rebound_to_newer_matching_room(monkeypatch):
    file_id = "c52e1167-f8de-4e03-bfef-9e3045cf8c60"
    requested_room_id = "22f1af6b-4d98-42d2-bd44-b7347be292a3"
    wrong_room = SimpleNamespace(
        id=requested_room_id,
        workspace_file_id=file_id,
        source_content_ref="oss://projects/repo/collab/source.xlsx",
        actor_type="user",
        actor_id="different-user",
        source_revision="b" * 64,
        created_at=datetime.now(UTC),
        closed_at=None,
    )

    class Result:
        def scalar_one_or_none(self):
            return None

    class FakeDb:
        async def execute(self, _statement):
            return Result()

        async def get(self, _model, _requested_id):
            return wrong_room

    async def fake_get_file(_db, requested_id):
        return SimpleNamespace(id=requested_id)

    monkeypatch.setattr(workspace_service, "get_file", fake_get_file)
    with pytest.raises(ValueError, match="no matching authorized edit room"):
        await office_edit.record_save_event(FakeDb(), {
            "event_id": "e" * 64, "file_id": file_id, "room_id": requested_room_id,
            "repository_id": "repo",
            "source_object_key": "projects/repo/collab/source.xlsx",
            "object_key": "projects/repo/assets/saved.xlsx", "version_id": None,
            "etag": "etag", "size": 10, "content_type": "application/octet-stream",
            "content_hash": "a" * 64,
            "user_id": office_edit.weboffice_user_id("user", "user-1"),
            "source_revision": "b" * 64,
            "integrity_algorithm": "crc64ecma", "integrity_value": "12345",
        })


@pytest.mark.asyncio
async def test_edit_session_binds_room_before_gateway_and_uses_renewable_lease(monkeypatch):
    _configure_office_edit(monkeypatch)
    office_edit._token_cache.clear()
    file = SimpleNamespace(
        id=uuid4(),
        workspace_id=uuid4(),
        path="共享/明细.xlsx",
        content_ref="oss://projects/repo/assets/source.xlsx",
        size=1024,
        current_version_id=uuid4(),
        deleted_at=None,
        metadata_={
            "binary": True,
            "name": "明细.xlsx",
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )

    class Result:
        def __init__(self, scalar=None):
            self.scalar = scalar

        def scalar_one_or_none(self):
            return self.scalar

    class FakeDb:
        def __init__(self):
            self.results = iter((Result(file), Result(None), Result(None)))
            self.room = None

        async def execute(self, _statement):
            return next(self.results)

        def add(self, value):
            self.room = value
            if value.id is None:
                value.id = uuid4()

        async def flush(self):
            return None

    db = FakeDb()
    captured = {}

    async def fake_token(_ref, **kwargs):
        # The exact durable room must already exist before the external call.
        assert db.room is not None
        assert kwargs["room_id"] == str(db.room.id)
        captured.update(kwargs)
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "refresh_context": "refresh-context",
            "source_version_id": None,
            "source_revision": "a" * 64,
        }

    monkeypatch.setattr(storage, "generate_weboffice_token", fake_token)
    before = datetime.now(UTC)
    result = await office_edit.create_edit_session(
        db, file, actor_type="user", actor_id="employee-1", client_open_id="open-client-1",
    )
    assert result["room_id"] == str(db.room.id)
    assert db.room.source_storage_version_id is None
    assert db.room.source_revision == "a" * 64
    assert before + timedelta(minutes=34) < db.room.expires_at < before + timedelta(minutes=36)
    assert captured["file_id"] == str(file.id)


@pytest.mark.asyncio
async def test_edit_session_gateway_failure_marks_room_non_blocking(monkeypatch):
    _configure_office_edit(monkeypatch)
    office_edit._token_cache.clear()
    file = SimpleNamespace(
        id=uuid4(), workspace_id=uuid4(), path="source.docx",
        content_ref="oss://projects/repo/assets/source.docx", size=100,
        current_version_id=uuid4(), deleted_at=None,
        metadata_={"binary": True, "name": "source.docx"},
    )

    class Result:
        def __init__(self, scalar=None):
            self.scalar = scalar

        def scalar_one_or_none(self):
            return self.scalar

    class FakeDb:
        def __init__(self):
            self.results = iter((Result(file), Result(None), Result(None)))
            self.room = None

        async def execute(self, _statement):
            return next(self.results)

        def add(self, value):
            self.room = value
            value.id = value.id or uuid4()

        async def flush(self):
            return None

    async def fail_token(*_args, **_kwargs):
        raise storage.StorageGatewayError("https://signed.example/secret?token=never-log-this")

    db = FakeDb()
    monkeypatch.setattr(storage, "generate_weboffice_token", fail_token)
    with pytest.raises(storage.StorageGatewayError):
        await office_edit.create_edit_session(
            db, file, actor_type="user", actor_id="employee-1", client_open_id="open-client-2",
        )
    assert db.room.status == "failed"
    assert "secret" not in (db.room.last_error or "")


@pytest.mark.asyncio
async def test_refresh_edit_session_requires_exact_room_and_renews_lease(monkeypatch):
    _configure_office_edit(monkeypatch)
    file = SimpleNamespace(
        id=uuid4(), path="source.pptx", content_ref="oss://projects/repo/assets/source.pptx",
        size=100, current_version_id=uuid4(), deleted_at=None,
        metadata_={"binary": True, "name": "source.pptx"},
    )
    room = SimpleNamespace(
        id=uuid4(), workspace_file_id=file.id, actor_type="user", actor_id="employee-1",
        status="open", expires_at=datetime.now(UTC) + timedelta(minutes=1),
        source_content_ref=file.content_ref, source_revision="b" * 64, last_error=None,
    )

    class Result:
        def scalar_one_or_none(self):
            return room

    class FakeDb:
        async def execute(self, _statement):
            return Result()

        async def flush(self):
            return None

    captured = {}

    async def fake_refresh(_ref, **kwargs):
        captured.update(kwargs)
        return {"source_revision": "b" * 64, "access_token": "new-access"}

    monkeypatch.setattr(storage, "refresh_weboffice_token", fake_refresh)
    before = datetime.now(UTC)
    await office_edit.refresh_edit_session(
        FakeDb(), file, actor_type="user", actor_id="employee-1",
        access_token="access-token", refresh_token="refresh-token",
        refresh_context="refresh-context", room_id=UUID(str(room.id)),
    )
    assert captured["room_id"] == str(room.id)
    assert before + timedelta(minutes=34) < room.expires_at < before + timedelta(minutes=36)


def _unversioned_save_fixture(*, external_current: bool = False):
    source_version = uuid4()
    file = SimpleNamespace(
        id=uuid4(), workspace_id=uuid4(), path="source.xlsx", size=100,
        content_ref="oss://projects/repo/collab/source.xlsx",
        content_hash="0" * 64, content=None, extracted_text=None,
        parse_status="ready", parse_kind="spreadsheet", parse_error=None,
        metadata_={"binary": True, "name": "source.xlsx"}, deleted_at=None,
        current_version_id=uuid4() if external_current else source_version,
    )
    room = SimpleNamespace(
        id=uuid4(), workspace_file_id=file.id, source_file_version_id=source_version,
        source_content_ref="oss://projects/repo/collab/source.xlsx",
        actor_type="user", actor_id="employee-1", source_revision="c" * 64,
        status="closing", final_file_version_id=None, reconciled_at=None,
        closed_at=None, expires_at=datetime.now(UTC) + timedelta(minutes=5), error=None,
    )
    event = SimpleNamespace(
        id=uuid4(), workspace_file_id=file.id, office_edit_room_id=room.id,
        repository_id="repo", source_object_key="projects/repo/collab/source.xlsx",
        object_key="projects/repo/assets/materialized.xlsx", source_user_id=office_edit.weboffice_user_id(
            "user", "employee-1"
        ), source_revision="c" * 64,
        notified_storage_version_id=None, notified_etag="etag-1", notified_size=321,
        notified_content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        notified_content_hash="d" * 64, notified_integrity_algorithm="crc64ecma",
        notified_integrity_value="123456", imm_version="2",
        event_time="2026-09-03T10:00:00Z", status="processing", error=None,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        resolved_storage_version_id=None, resolved_file_version_id=None,
    )
    return file, room, event


@pytest.mark.asyncio
async def test_unversioned_office_save_reconciles_by_unique_ref_and_crc(monkeypatch):
    file, room, event = _unversioned_save_fixture()

    class Result:
        def __init__(self, *, scalar=None, rows=None):
            self.scalar = scalar
            self.rows = rows or []

        def scalar_one_or_none(self):
            return self.scalar

        def scalars(self):
            return self.rows

    class FakeDb:
        def __init__(self):
            self.results = iter((Result(scalar=file), Result(rows=[]), Result(scalar=None)))

        async def execute(self, _statement):
            return next(self.results)

        async def get(self, model, requested_id):
            assert str(requested_id) == str(room.id)
            return room

        async def flush(self):
            return None

    async def fake_resolve(*_args, **_kwargs):
        return {
            "version_id": None, "etag": "etag-1", "size": 321,
            "content_type": event.notified_content_type, "content_hash": "d" * 64,
            "integrity_algorithm": "crc64ecma", "integrity_value": "123456",
        }

    async def fake_create_version(_db, target, **_kwargs):
        version = SimpleNamespace(id=uuid4(), storage_version_id="sentinel", storage_etag=None)
        target.current_version_id = version.id
        return version

    monkeypatch.setattr(storage, "resolve_weboffice_version", fake_resolve)
    monkeypatch.setattr(workspace_service, "create_file_version", fake_create_version)
    monkeypatch.setattr(office_edit, "_actor_can_still_update", lambda *_args: _async_true())
    outcome = await office_edit.reconcile_save_event(FakeDb(), event)
    assert outcome == "completed"
    assert event.resolved_storage_version_id is None
    assert event.resolved_file_version_id == room.final_file_version_id
    assert file.metadata_["integrity_algorithm"] == "crc64ecma"
    assert file.metadata_["storage_version_id"] is None


@pytest.mark.asyncio
async def test_office_save_cannot_coalesce_after_external_file_advance(monkeypatch):
    file, room, event = _unversioned_save_fixture(external_current=True)

    class Result:
        def __init__(self, *, scalar=None, rows=None):
            self.scalar = scalar
            self.rows = rows or []

        def scalar_one_or_none(self):
            return self.scalar

        def scalars(self):
            return self.rows

    class FakeDb:
        def __init__(self):
            self.results = iter((Result(scalar=file), Result(rows=[])))

        async def execute(self, _statement):
            return next(self.results)

        async def get(self, _model, _requested_id):
            return room

    async def fake_resolve(*_args, **_kwargs):
        return {
            "version_id": None, "etag": "etag-1", "size": 321,
            "content_type": event.notified_content_type, "content_hash": "d" * 64,
            "integrity_algorithm": "crc64ecma", "integrity_value": "123456",
        }

    monkeypatch.setattr(storage, "resolve_weboffice_version", fake_resolve)
    monkeypatch.setattr(office_edit, "_actor_can_still_update", lambda *_args: _async_true())
    outcome = await office_edit.reconcile_save_event(FakeDb(), event)
    assert outcome == "conflict"
    assert event.error == "logical file advanced outside this edit source"
    assert room.final_file_version_id is None


@pytest.mark.asyncio
async def test_office_save_rechecks_live_actor_permission_before_materializing(monkeypatch):
    file, room, event = _unversioned_save_fixture()

    class Result:
        def scalar_one_or_none(self):
            return file

    class FakeDb:
        async def execute(self, _statement):
            return Result()

        async def get(self, _model, _requested_id):
            return room

    async def denied(*_args):
        return False

    monkeypatch.setattr(office_edit, "_actor_can_still_update", denied)
    outcome = await office_edit.reconcile_save_event(FakeDb(), event)
    assert outcome == "conflict"
    assert event.error == "edit permission revoked before save"
    assert room.status == "failed"
    assert room.expires_at <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_office_reconcile_worker_parks_when_feature_is_disabled(monkeypatch):
    from app.workers import office_edit_reconcile

    class ParkedForTestError(Exception):
        pass

    async def stop_after_first_sleep(seconds):
        assert seconds == 60
        raise ParkedForTestError

    monkeypatch.setattr(settings, "workspace_weboffice_edit_enabled", False)
    monkeypatch.setattr(office_edit_reconcile.asyncio, "sleep", stop_after_first_sleep)
    with pytest.raises(ParkedForTestError):
        await office_edit_reconcile.run_forever()


def test_office_callback_accepts_gateway_128_character_ordering_fields():
    from pydantic import ValidationError

    from app.api.office_edit import OfficeSaveEventReceipt

    common = {
        "event_id": "e" * 64,
        "file_id": str(uuid4()),
        "room_id": str(uuid4()),
        "repository_id": "repo",
        "source_object_key": "projects/repo/collab/source.xlsx",
        "object_key": "projects/repo/assets/saved.xlsx",
        "version_id": None,
        "etag": "etag",
        "size": 10,
        "content_type": "application/octet-stream",
        "content_hash": "a" * 64,
        "user_id": "user",
        "source_revision": "b" * 64,
        "integrity_algorithm": "crc64ecma",
        "integrity_value": "12345",
    }
    receipt = OfficeSaveEventReceipt(
        **common, imm_version="v" * 128, event_time="t" * 128,
    )
    assert len(receipt.imm_version) == 128
    with pytest.raises(ValidationError):
        OfficeSaveEventReceipt(**common, imm_version="v" * 129)


@pytest.mark.asyncio
async def test_inspect_object_preserves_gateway_verified_exact_format(monkeypatch):
    _configure(monkeypatch)

    class SignedResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "url": "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/7/output.xlsx",
                "etag": "etag-1", "content_type": "application/octet-stream",
                "integrity_algorithm": "crc64ecma", "integrity_value": "12345",
                "detected_format": "xlsx", "format_verified": True,
            }

    class RangeResponse:
        headers = {"content-range": "bytes 0-0/42"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return SignedResponse()

        def stream(self, *_args, **_kwargs):
            return RangeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    actual = await storage.inspect_object("oss://projects/7/output.xlsx")
    assert actual["size"] == 42
    assert actual["detected_format"] == "xlsx"
    assert actual["format_verified"] is True


@pytest.mark.asyncio
async def test_browser_signed_download_uses_acceleration_with_public_fallback(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "url": "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/7/assets/deck.pptx?sig=browser",
                "headers": {},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            assert url.endswith("/v1/downloads/sign")
            assert kwargs["json"] == {
                "object_key": "projects/7/assets/deck.pptx",
                "expires_in_seconds": 900,
            }
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    signed = await storage.get_browser_signed_download("oss://projects/7/assets/deck.pptx")
    assert signed["url"].startswith("https://bucket.oss-accelerate.aliyuncs.com/")
    assert "-internal" not in signed["url"]
    assert signed["fallback_url"].startswith("https://bucket.oss-cn-hongkong.aliyuncs.com/")


@pytest.mark.asyncio
async def test_browser_signed_download_rewrites_accelerated_gateway_url_to_public_fallback(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "url": "https://bucket.oss-accelerate.aliyuncs.com/projects/7/assets/deck.pptx?sig=browser",
                "headers": {},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    signed = await storage.get_browser_signed_download("oss://projects/7/assets/deck.pptx")
    assert signed["url"].startswith("https://bucket.oss-accelerate.aliyuncs.com/")
    assert signed["fallback_url"].startswith("https://bucket.oss-cn-hongkong.aliyuncs.com/")


@pytest.mark.asyncio
async def test_large_browser_upload_requests_parallel_multipart(monkeypatch):
    _configure(monkeypatch)
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "session_id": "multipart-1",
                "object_key": "projects/7/assets/deck.pptx",
                "part_size": 100 * 1024 * 1024,
                "expected_parts": 5,
                "expires_at": "2026-09-01T00:00:00Z",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured.update({"url": url, "headers": kwargs["headers"], "json": kwargs["json"]})
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    result = await storage.sign_browser_upload(
        filename="deck.pptx",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        size_bytes=500 * 1024 * 1024,
    )

    assert captured["url"].endswith("/v1/multipart/initiate")
    assert captured["headers"]["X-Storage-Subject"] == "ai-platform-control-plane"
    assert captured["json"]["force_multipart"] is True
    assert captured["json"]["part_size_bytes"] == 8 * 1024 * 1024
    assert result["method"] == "MULTIPART"
    assert result["expected_parts"] == 5


@pytest.mark.asyncio
async def test_large_browser_upload_uses_small_parts_in_weak_network_mode(monkeypatch):
    _configure(monkeypatch)
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "session_id": "multipart-weak",
                "object_key": "projects/7/assets/deck.pptx",
                "part_size": 1024 * 1024,
                "expected_parts": 101,
                "expires_at": "2026-09-01T00:00:00Z",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            captured.update(kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    result = await storage.sign_browser_upload(
        filename="deck.pptx",
        content_type="application/octet-stream",
        size_bytes=101 * 1024 * 1024,
        weak_network=True,
    )
    assert captured["part_size_bytes"] == 2 * 1024 * 1024
    assert result["part_size"] == 1024 * 1024


@pytest.mark.asyncio
async def test_stream_signed_download_proxies_internal_object_in_chunks(monkeypatch):
    _configure(monkeypatch)

    class FakeStreamResponse:
        headers = {"content-length": "8"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, _chunk_size):
            yield b"original"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, method, url, **kwargs):
            assert method == "GET"
            assert "oss-cn-hongkong-internal" in url
            assert kwargs["headers"] == {"x-test": "download"}
            return FakeStreamResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    chunks = [chunk async for chunk in storage.stream_signed_download(
        "https://bucket.oss-cn-hongkong-internal.aliyuncs.com/report.xlsx?sig=2",
        headers={"x-test": "download"},
        max_bytes=100,
    )]
    assert chunks == [b"original"]


@pytest.mark.asyncio
async def test_workspace_loads_external_bytes_and_verifies_hash(monkeypatch):
    raw = b"external file"
    file = SimpleNamespace(
        content_ref="oss://projects/7/assets/file.pdf",
        content=None,
        content_hash=hashlib.sha256(raw).hexdigest(),
        metadata_={"binary": True},
    )

    async def fake_download(_ref: str, *, version_id=None) -> bytes:
        assert version_id is None
        return raw

    monkeypatch.setattr(storage, "download_bytes", fake_download)
    assert await workspace_service.load_file_bytes(file) == raw


@pytest.mark.asyncio
async def test_workspace_rejects_external_hash_mismatch(monkeypatch):
    file = SimpleNamespace(
        content_ref="oss://projects/7/assets/file.pdf",
        content=None,
        content_hash="0" * 64,
        metadata_={"binary": True},
    )

    async def fake_download(_ref: str, *, version_id=None) -> bytes:
        assert version_id is None
        return b"tampered"

    monkeypatch.setattr(storage, "download_bytes", fake_download)
    with pytest.raises(workspace_service.WorkspaceFileUploadError, match="完整性校验失败"):
        await workspace_service.load_file_bytes(file)


@pytest.mark.asyncio
async def test_runner_input_signs_the_exact_historical_storage_version(monkeypatch):
    from app.agents.graph import nodes

    captured = {}

    async def fake_sign(ref: str, *, version_id=None):
        captured.update({"ref": ref, "version_id": version_id})
        return {"url": "https://internal.example/signed", "headers": {}}

    monkeypatch.setattr(storage, "get_signed_download", fake_sign)
    file = SimpleNamespace(
        id="c52e1167-f8de-4e03-bfef-9e3045cf8c60",
        path="历史/报表.xlsx",
        size=nodes.RUNNER_INLINE_FILE_BYTES + 1,
        content_ref="oss://projects/7/assets/report.xlsx",
        metadata_={"name": "报表.xlsx", "storage_version_id": "oss-history-v3"},
    )
    result = await nodes._runner_input(file)
    assert captured == {
        "ref": "oss://projects/7/assets/report.xlsx",
        "version_id": "oss-history-v3",
    }
    assert result["download_url"] == "https://internal.example/signed"


@pytest.mark.asyncio
async def test_object_listing_is_normalized_for_orphan_reconciliation(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [
                    {"object_key": "projects/1/kept.bin", "size_bytes": 12, "created_at": "2026-01-01"},
                    {"invalid": True},
                ],
                "next_cursor": "page-2",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **kwargs):
            assert url.endswith("/v1/objects")
            assert kwargs["headers"]["Authorization"] == "Bearer project-token"
            assert kwargs["params"]["limit"] == 500
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    result = await storage.list_project_objects(older_than=datetime.now(UTC))
    assert result == {
        "items": [{"object_key": "projects/1/kept.bin", "size": 12, "created_at": "2026-01-01"}],
        "next_cursor": "page-2",
    }


@pytest.mark.asyncio
async def test_object_listing_safely_skips_legacy_gateway(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        status_code = 404

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    assert await storage.list_project_objects(older_than=datetime.now(UTC)) is None
