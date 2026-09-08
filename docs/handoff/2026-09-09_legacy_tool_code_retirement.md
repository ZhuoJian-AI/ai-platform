# Legacy tool code retirement handoff

## Scope

- Branch: `refactor/retire-legacy-tools-20260909`
- Base: `b672b79`
- Removed the Connector, ToolEndpoint, Data Interface, ToolCallLog and application tool-binding code paths.
- Did not change migrations, Team, Office/OAuth, frontend code, deployment files or the subsystem-builder Skill.

## Result

- Connector and Data Interface routers, ORM models, schemas, services and endpoint executor/parser files are gone.
- The hidden terminal Data Interface tombstone and application tool-binding 410 route are gone; representative retired routes now return 404 and are absent from OpenAPI.
- Application overview keeps its existing response envelope but now describes Manifest Actions and recent ActionRequests.
- Tool monitoring now aggregates SkillExecution and ActionRequest records while retaining Skill inventory and per-Action breakdowns.
- Business assistants still receive only current-page authorized Manifest Actions; personal/custom assistants retain scoped uploaded Skills and executable Skill packages.
- Legacy `bound_endpoint_ids` is ignored by the Skill parser and retained only in import sanitization so an old package cannot reactivate an Endpoint.

## Verification

- `uv run pytest -q`: `535 passed, 15 skipped`.
- Focused application/monitor/retirement tests: `34 passed`.
- Focused Assistant Core/Manifest Action/Skill tests: `102 passed`.
- Changed-file Ruff check: passed.
- Full `ruff check app/ tests/` still reports 12 pre-existing findings in routing policies, DLP, memory, proxy adapters and unrelated services; none are in this change set.
- `git diff --check`: passed.

## Follow-up boundaries

- The physical database tables remain because this branch intentionally contains no Alembic changes. A later contract migration may drop them after this code lands.
- `nodes.py` still catches `workspace_service.WorkspaceFileActiveEditConflict` in six Office/workspace write paths. Those are Office retirement leftovers for the coordinating task to remove; this branch did not touch them.
- Tests used an isolated PostgreSQL 18 cluster on local port 5434. The server was stopped after tests. Sandbox policy blocked recursive deletion of `D:\Agent_Project\_codex_test_pg_connector_retire`, so the stopped temporary cluster directory remains for the coordinator to remove.
