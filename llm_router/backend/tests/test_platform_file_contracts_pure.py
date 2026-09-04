from __future__ import annotations

import base64
import io
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.agents.graph import nodes
from app.api import terminal
from app.auth.user_auth import current_user_for_user
from app.config import settings
from app.main import _redacted_validation_errors, conceal_stable_file_forbidden
from app.models.workspace import WorkspaceFileVersion
from app.schemas.workspace import (
    WorkspaceFileCreate,
    WorkspaceFileDeleteRequest,
    WorkspaceFileRestoreRequest,
    WorkspaceUploadInitiate,
)
from app.services import platform_extension_catalog, workspace_governance_service, workspace_service


@pytest.fixture(autouse=True)
def db_engine():
    yield


def test_workspace_platform_catalog_exposes_all_canonical_atomic_tools():
    group = next(
        item for item in platform_extension_catalog.SYSTEM_TOOL_GROUPS
        if item["slug"] == "workspace-files"
    )
    assert {
        "workspace_list",
        "workspace_search",
        "workspace_get_file",
        "workspace_read_file",
        "workspace_create_file",
        "workspace_update_file",
        "workspace_rename_file",
        "workspace_move_file",
        "workspace_copy_file",
        "workspace_delete_file",
        "workspace_list_versions",
        "workspace_restore_version",
    }.issubset(set(group["tools"]))


def test_explicit_upload_replacement_identity_is_all_or_none():
    common = {
        "path": "共享/明细.xlsx",
        "filename": "明细.xlsx",
        "content_type": "application/octet-stream",
        "size": 1024,
    }
    with pytest.raises(ValidationError):
        WorkspaceUploadInitiate(**common, target_file_id=uuid4())
    request = WorkspaceUploadInitiate(
        **common,
        target_file_id=uuid4(),
        base_version_id=uuid4(),
        idempotency_key="replace-version-0001",
    )
    assert request.target_file_id is not None


def test_plain_text_mutation_rejects_known_binary_but_allows_code():
    binary = SimpleNamespace(
        path="共享/明细.xlsx",
        content="UEsDBA==",
        parse_kind=None,
        metadata_={
            "binary": True,
            "name": "明细.xlsx",
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        workspace_service._assert_plain_text_update_supported(binary)
    with pytest.raises(workspace_service.WorkspaceFileMetadataConflict):
        workspace_service._merge_update_metadata(
            binary, {"binary": False, "name": "明细.txt", "mime": "text/plain"},
        )
    # A separate rename changes only the human path/name.  Persisted binary
    # provenance still wins, so renaming an Office file to .txt cannot make the
    # generic UTF-8 endpoint corrupt it.
    renamed_binary = SimpleNamespace(
        path="共享/明细.txt", content=None, parse_kind="spreadsheet",
        metadata_={
            "binary": True, "name": "明细.txt",
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        workspace_service._assert_plain_text_update_supported(renamed_binary)
    source_code = SimpleNamespace(
        path="scripts/report.py", content="print('ok')", parse_kind="text",
        metadata_={"name": "report.py", "mime": "application/octet-stream"},
    )
    workspace_service._assert_plain_text_update_supported(source_code)


def test_office_edit_capability_is_server_owned_and_fail_closed(monkeypatch):
    file = SimpleNamespace(
        path="共享/明细.xlsx", content_ref="oss://projects/repo/assets/source.xlsx",
        current_version_id=uuid4(), size=1024,
        metadata_={"binary": True, "name": "明细.xlsx"},
    )
    monkeypatch.setattr(settings, "workspace_weboffice_edit_enabled", True)
    monkeypatch.setattr(settings, "workspace_object_storage_enabled", True)
    monkeypatch.setattr(settings, "storage_gateway_url", "https://storage.example.test")
    monkeypatch.setattr(settings, "storage_project_token", "project-token")
    monkeypatch.setattr(settings, "workspace_office_event_callback_secret", "c" * 32)
    assert workspace_service.office_edit_enabled(file, can_update=True)
    assert not workspace_service.office_edit_enabled(file, can_update=False)
    monkeypatch.setattr(settings, "workspace_office_event_callback_secret", "")
    assert not workspace_service.office_edit_enabled(file, can_update=True)


def test_terminal_delete_contract_requires_explicit_version_and_key():
    with pytest.raises(ValidationError):
        WorkspaceFileDeleteRequest(base_version_id=uuid4())
    request = WorkspaceFileDeleteRequest(
        base_version_id=uuid4(), idempotency_key="delete-file-0001",
    )
    assert request.idempotency_key == "delete-file-0001"


def test_version_restore_contract_requires_explicit_version_and_key():
    with pytest.raises(ValidationError):
        WorkspaceFileRestoreRequest()
    with pytest.raises(ValidationError):
        WorkspaceFileRestoreRequest(base_version_id=uuid4())
    request = WorkspaceFileRestoreRequest(
        base_version_id=uuid4(), idempotency_key="restore-file-0001",
    )
    assert request.idempotency_key == "restore-file-0001"


@pytest.mark.asyncio
async def test_deleted_user_never_falls_back_to_stale_principal():
    class Result:
        def scalar_one_or_none(self):
            return None

    class FakeDb:
        async def execute(self, _statement):
            return Result()

    with pytest.raises(HTTPException) as raised:
        await current_user_for_user(FakeDb(), SimpleNamespace(id=uuid4(), is_active=True))
    assert raised.value.status_code == 401


@pytest.mark.asyncio
async def test_plain_text_create_cannot_claim_binary_extension():
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        await workspace_service.upsert_file(
            SimpleNamespace(),
            SimpleNamespace(id=uuid4()),
            WorkspaceFileCreate(path="伪造/报告.odp", content="not a presentation"),
        )


@pytest.mark.asyncio
async def test_plain_text_create_cannot_hide_binary_path_with_text_metadata():
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        await workspace_service.upsert_file(
            SimpleNamespace(),
            SimpleNamespace(id=uuid4()),
            WorkspaceFileCreate(
                path="伪造/报告.xlsx",
                content="not a workbook",
                metadata={"name": "safe.txt", "mime": "text/plain"},
            ),
        )

    persisted = SimpleNamespace(
        path="共享/说明.pdf",
        content=None,
        parse_kind="text",
        metadata_={"name": "safe.txt", "mime": "text/plain"},
    )
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        workspace_service._assert_plain_text_update_supported(persisted)


def test_artifact_replacement_uses_real_inline_container_not_declared_mime():
    target = SimpleNamespace(
        path="共享/明细.xlsx",
        metadata_={
            "binary": True,
            "name": "明细.xlsx",
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )
    declared_sheet = {
        "binary": True,
        "name": "明细.xlsx",
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        workspace_service._assert_artifact_replacement_compatible(
            target,
            declared_sheet,
            content=base64.b64encode(b"plain text").decode(),
            content_ref=None,
        )

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    workspace_service._assert_artifact_replacement_compatible(
        target,
        declared_sheet,
        content=base64.b64encode(stream.getvalue()).decode(),
        content_ref=None,
    )


def test_content_ref_replacement_requires_server_verified_format():
    target = SimpleNamespace(
        path="共享/说明.pdf",
        metadata_={"binary": True, "name": "说明.pdf", "mime": "application/pdf"},
    )
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        workspace_service._assert_artifact_replacement_compatible(
            target,
            {"binary": True, "mime": "application/pdf"},
            content=None,
            content_ref="oss://projects/repo/output.pdf",
        )
    workspace_service._assert_artifact_replacement_compatible(
        target,
        {
            "binary": True,
            "mime": "application/pdf",
            "artifact_format_verified": True,
            "detected_artifact_format": "pdf",
        },
        content=None,
        content_ref="oss://projects/repo/output.pdf",
    )


def test_artifact_replacement_rejects_same_family_extension_and_generic_ole():
    target = SimpleNamespace(
        path="共享/明细.xlsx",
        metadata_={
            "binary": True,
            "name": "明细.xlsx",
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        workspace_service._assert_artifact_replacement_compatible(
            target,
            {
                "binary": True,
                "artifact_format_verified": True,
                "detected_artifact_format": "xlsm",
            },
            content=None,
            content_ref="oss://projects/repo/macro.xlsm",
        )
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        workspace_service._assert_artifact_replacement_compatible(
            target,
            {
                "binary": True,
                "artifact_format_verified": True,
                "detected_artifact_format": "ole_compound",
            },
            content=None,
            content_ref="oss://projects/repo/unknown-ole.bin",
        )


def test_validation_errors_do_not_reflect_input_or_context():
    error = SimpleNamespace(errors=lambda: [{
        "type": "value_error", "loc": ("body", "access_token"),
        "msg": "Value error", "input": "super-secret-token",
        "ctx": {"error": "signed-url?token=secret"},
    }])
    redacted = _redacted_validation_errors(error)
    assert redacted == [{
        "type": "value_error", "loc": ("body", "access_token"), "msg": "Value error",
    }]
    assert "secret" not in str(redacted)


@pytest.mark.asyncio
async def test_forbidden_stable_file_id_is_concealed_as_not_found():
    file_id = uuid4()
    request = Request({
        "type": "http", "method": "GET",
        "path": f"/api/v1/terminal/files/{file_id}",
        "headers": [], "query_string": b"", "server": ("test", 80),
        "client": ("test", 1), "scheme": "http",
    })
    response = await conceal_stable_file_forbidden(
        request, HTTPException(status_code=403, detail="update denied"),
    )
    assert response.status_code == 404
    assert b"update denied" not in response.body


@pytest.mark.asyncio
async def test_public_share_never_renders_same_origin_active_html(monkeypatch):
    version = SimpleNamespace(content_ref=None)

    async def resolve_share(_db, _token):
        return version, "payload.html", "text/html"

    async def load_bytes(_version):
        return b"<script>window.__stored_xss = true</script>"

    monkeypatch.setattr(workspace_governance_service, "resolve_share", resolve_share)
    monkeypatch.setattr(workspace_governance_service, "load_version_bytes", load_bytes)
    response = await terminal.public_workspace_share_endpoint("opaque", SimpleNamespace())
    assert response.media_type == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_recursive_delete_checks_every_active_room_before_any_tombstone(monkeypatch):
    first = SimpleNamespace(
        id=uuid4(), current_version_id=uuid4(), deleted_at=None, purge_after=None,
        deleted_by_user_id=None, deleted_by_admin_id=None,
    )
    blocked = SimpleNamespace(
        id=uuid4(), current_version_id=uuid4(), deleted_at=None, purge_after=None,
        deleted_by_user_id=None, deleted_by_admin_id=None,
    )

    async def assert_room(_db, file):
        if file is blocked:
            raise workspace_service.WorkspaceFileActiveEditConflict(
                "active", room_id=uuid4(), current_version_id=file.current_version_id,
            )

    monkeypatch.setattr(workspace_service, "assert_no_active_office_room", assert_room)
    with pytest.raises(workspace_service.WorkspaceFileActiveEditConflict):
        await workspace_service._mark_files_deleted_locked(
            SimpleNamespace(), [first, blocked], user_id=uuid4(),
        )
    assert first.deleted_at is None
    assert blocked.deleted_at is None


@pytest.mark.asyncio
async def test_only_trusted_same_org_live_tool_files_become_artifacts(monkeypatch):
    org_id = uuid4()
    workspace_id = uuid4()
    file_id = uuid4()
    version_id = uuid4()
    workspace = SimpleNamespace(
        id=workspace_id, organization_id=org_id, name="个人空间", slug="personal",
    )
    file = SimpleNamespace(
        id=file_id, workspace_id=workspace_id, path="结果/report.txt",
        metadata_={"name": "report.txt", "mime": "text/plain"},
        current_version_id=version_id, size=2, parse_status="ready",
        created_at=datetime.now(UTC), deleted_at=None,
    )
    version = SimpleNamespace(
        id=version_id, workspace_file_id=file_id, version_no=1,
        metadata_=dict(file.metadata_), size=2, parse_status="ready",
    )

    class FakeDb:
        async def get(self, model, value):
            if model is WorkspaceFileVersion and str(value) == str(version_id):
                return version
            return None

    async def get_file(_db, value):
        return file if str(value) == str(file_id) else None

    async def get_workspace(_db, value):
        return workspace if str(value) == str(workspace_id) else None

    db = FakeDb()
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db})
    monkeypatch.setattr(workspace_service, "get_file", get_file)
    monkeypatch.setattr(workspace_service, "get_workspace", get_workspace)
    common = {
        "file_id": str(file_id), "version_id": str(version_id), "scope": "turn",
        "follow_latest": True, "source": "tool_result", "operation": "create",
        "workspace_id": str(workspace_id),
    }
    verified, artifacts = await nodes._verified_tool_file_records(
        {"org_id": str(org_id), "workspace_id": str(workspace_id)},
        [
            {**common, "tool_name": "workspace_create_file"},
            {**common, "tool_name": "untrusted_connector"},
        ],
        None,
        task_id=str(uuid4()),
        task_title="测试",
        executed_skills=[],
    )
    assert len(verified) == 1
    assert len(artifacts) == 1
    assert artifacts[0]["file_id"] == str(file_id)


@pytest.mark.asyncio
async def test_copy_replay_card_keeps_original_result_without_later_move_leak(monkeypatch):
    org_id = uuid4()
    original_workspace_id = uuid4()
    current_workspace_id = uuid4()
    file_id = uuid4()
    version_id = uuid4()
    current_workspace = SimpleNamespace(
        id=current_workspace_id, organization_id=org_id, name="秘密目标", slug="secret",
    )
    original_workspace = SimpleNamespace(
        id=original_workspace_id, organization_id=org_id, name="技术部", slug="technology",
    )
    file = SimpleNamespace(
        id=file_id, workspace_id=current_workspace_id, path="后来/移动位置.txt",
        metadata_={"name": "后来位置.txt", "mime": "text/plain"},
        current_version_id=uuid4(), size=2, parse_status="ready",
        created_at=datetime.now(UTC), deleted_at=None,
    )
    version = SimpleNamespace(
        id=version_id, workspace_file_id=file_id, version_no=1,
        metadata_={"name": "交付.txt", "mime": "text/plain"},
        size=2, parse_status="ready",
    )
    mutation = SimpleNamespace(
        workspace_id=original_workspace_id,
        result={"target_path": "原始/交付.txt"},
    )

    class Result:
        def scalar_one_or_none(self):
            return mutation

    class FakeDb:
        async def get(self, model, value):
            if model is WorkspaceFileVersion and str(value) == str(version_id):
                return version
            return None

        async def execute(self, _statement):
            return Result()

    async def get_file(_db, value):
        return file if str(value) == str(file_id) else None

    async def get_workspace(_db, value):
        if str(value) == str(current_workspace_id):
            return current_workspace
        if str(value) == str(original_workspace_id):
            return original_workspace
        return None

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": FakeDb()})
    monkeypatch.setattr(workspace_service, "get_file", get_file)
    monkeypatch.setattr(workspace_service, "get_workspace", get_workspace)
    verified, artifacts = await nodes._verified_tool_file_records(
        {"org_id": str(org_id), "workspace_id": str(current_workspace_id)},
        [{
            "file_id": str(file_id), "version_id": str(version_id), "scope": "turn",
            "follow_latest": True, "source": "tool_result", "operation": "copy",
            "tool_name": "workspace_copy_file",
        }],
        None,
        task_id=str(uuid4()),
        task_title="测试",
        executed_skills=[],
    )
    assert verified[0]["workspace_id"] == str(original_workspace_id)
    assert verified[0]["canonical_path"] == "技术部:/原始/交付.txt"
    assert artifacts[0]["workspace_name"] == "技术部"
    assert "秘密目标" not in str(artifacts)


@pytest.mark.asyncio
async def test_create_replay_reauthorizes_live_location_and_returns_original_snapshot(monkeypatch):
    original_workspace_id = uuid4()
    current_workspace_id = uuid4()
    file_id = uuid4()
    result_version_id = uuid4()
    later_version_id = uuid4()
    principal = SimpleNamespace(id=uuid4())
    original_workspace = SimpleNamespace(
        id=original_workspace_id, name="技术部", slug="technology",
    )
    current_workspace = SimpleNamespace(
        id=current_workspace_id, name="秘密空间", slug="secret",
    )
    live = SimpleNamespace(
        id=file_id, workspace_id=current_workspace_id, path="后来/秘密.txt",
        current_version_id=later_version_id, created_at=datetime.now(UTC),
        metadata_={"name": "秘密.txt"}, size=99, content_hash="b" * 64,
        content_ref="oss://later", content=None, extracted_text=None,
        parse_status="ready", parse_kind="text", parse_error=None,
    )
    result_version = SimpleNamespace(
        id=result_version_id, workspace_file_id=file_id, version_no=1,
        storage_version_id=None, storage_etag=None, size=2,
        content_hash="a" * 64, content_ref="oss://original", content=None,
        extracted_text="ok", parse_status="ready", parse_kind="text",
        parse_error=None, metadata_={"name": "交付.txt"},
        created_at=datetime.now(UTC),
    )
    mutation = SimpleNamespace(
        result_file_id=file_id, result_version_id=result_version_id,
        workspace_id=original_workspace_id,
        result={"workspace_id": str(original_workspace_id), "path": "原始/交付.txt"},
    )

    class FakeDb:
        async def get(self, model, value):
            if model is WorkspaceFileVersion and str(value) == str(result_version_id):
                return result_version
            return None

    async def get_file(_db, value):
        return live if str(value) == str(file_id) else None

    async def get_workspace(_db, value):
        if str(value) == str(current_workspace_id):
            return current_workspace
        if str(value) == str(original_workspace_id):
            return original_workspace
        return None

    async def fresh(_db, _user):
        return principal

    allowed = {str(current_workspace_id), str(original_workspace_id)}

    async def capabilities(_db, workspace, _principal):
        return {"read": str(workspace.id) in allowed}

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": FakeDb()})
    monkeypatch.setattr(nodes, "_fresh_user_principal", fresh)
    monkeypatch.setattr(workspace_service, "get_file", get_file)
    monkeypatch.setattr(workspace_service, "get_workspace", get_workspace)
    monkeypatch.setattr(nodes.workspace_permission_service, "capabilities", capabilities)

    snapshot, workspace, _ = await nodes._authorized_create_replay(
        {"workspace_id": str(original_workspace_id)}, mutation, principal,
    )
    assert snapshot.path == "原始/交付.txt"
    assert snapshot.current_version_id == result_version_id
    assert workspace.id == original_workspace_id
    assert "秘密" not in snapshot.path

    allowed.remove(str(current_workspace_id))
    denied, denied_workspace, _ = await nodes._authorized_create_replay(
        {"workspace_id": str(original_workspace_id)}, mutation, principal,
    )
    assert denied is None
    assert denied_workspace is None


@pytest.mark.asyncio
async def test_concurrent_mutation_claim_replays_unique_winner_instead_of_500():
    organization_id = uuid4()
    actor_id = uuid4()
    workspace = SimpleNamespace(id=uuid4(), organization_id=organization_id)
    file = SimpleNamespace(id=uuid4())
    payload = {"target_path": "result.txt"}
    request_hash = workspace_service._stable_request_hash({"operation": "copy", **payload})
    winner = SimpleNamespace(
        request_hash=request_hash, operation="copy", status="completed",
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class Savepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _kind, _error, _traceback):
            return False

    class FakeDb:
        def __init__(self):
            self.lookups = iter((None, winner))

        async def execute(self, _statement):
            return Result(next(self.lookups))

        def begin_nested(self):
            return Savepoint()

        def add(self, _value):
            return None

        async def flush(self):
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    mutation, replayed = await workspace_service.begin_file_mutation(
        FakeDb(), workspace=workspace, file=file, actor_type="user",
        actor_id=str(actor_id), operation="copy", idempotency_key="copy-race-0001",
        payload=payload,
    )
    assert mutation is winner
    assert replayed is True


@pytest.mark.asyncio
async def test_concurrent_same_path_create_returns_the_winning_file_conflict():
    winner = SimpleNamespace(id=uuid4(), current_version_id=uuid4())

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class Savepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _kind, _error, _traceback):
            return False

    class FakeDb:
        def __init__(self):
            self.results = iter((None, winner))

        async def execute(self, _statement):
            return Result(next(self.results))

        def begin_nested(self):
            return Savepoint()

        def add(self, _value):
            return None

        async def flush(self):
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    workspace = SimpleNamespace(id=uuid4())
    with pytest.raises(workspace_service.WorkspaceFilePathConflict) as raised:
        await workspace_service.upsert_file(
            FakeDb(), workspace,
            workspace_service.WorkspaceFileCreate(path="共享/同名.txt", content="data"),
        )
    assert raised.value.file_id == str(winner.id)
    assert raised.value.current_version_id == str(winner.current_version_id)
