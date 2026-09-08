# Platform slim stage-1 release handoff

- Owner: `@codex-platform-slim-e2e`
- Task: `PLATFORM-SLIM-E2E-20260909`
- Scope: current `ai-platform` repository and Coolify staging application only.
- Source image revision: `25fbb776668b`
- Stage-1 manifest commit: `fda64df`
- Deployment rules revision: `c948cd2`

## Included behavior

- Restores upgraded-database employee creation compatibility and classifies real PostgreSQL constraint failures instead of mapping every `IntegrityError` to a duplicate username.
- Removes retired DSH, connector, data interface, ontology, judge, MCP/OAuth, team, online Office editing and compatibility runtime surfaces while keeping the native Assistant Core, workspaces, RAG, uploaded Skills, Manifest Actions, Runtime and ECS Publisher.
- Integrates the separately reviewed subsystem specialist-AI implementation without changing any business subsystem or Skill repository.
- Splits the largest assistant-node and Terminal implementations into smaller behavior-equivalent modules.
- Adds migration preflight/recovery checks and the irreversible `0075_retired_schema_contract` migration.
- Keeps exactly nine Coolify services and removes development-only packages from runtime images.

## Verification completed before stage 1

- Backend full suite against isolated PostgreSQL and Redis: `525 passed`.
- Frontend typecheck, twelve regression scripts and production build: passed.
- Registry-first images are `linux/amd64`, have revision `25fbb776668b` and contain no `pytest`, `ruff`, Playwright, Node or npm runtime dependency.
- Isolated nine-service stack `aiptmp25fbb776` passed:
  - empty database upgraded through the full `0001` to `0075` chain;
  - `alembic check` reported no pending operations;
  - a second upgrade was a no-op;
  - retired tables were absent and protected core tables were present;
  - all nine services and the frontend health endpoint were healthy.
- Staging database backup was written to `/root/ai-platform-backups/20260909-slim/ai-platform-staging-pre-0074-20260909-0440.dump` with SHA-256 `3c9fdd596ed395c103d0ad8662c9555bde31c228574f7ff27dce6dbc5e8534ba`; `pg_restore --list` and a restore/upgrade rehearsal passed.

## Stage-1 immutable images

- Backend: `sha256:74963146d282a485a98fd262f5d4abf250827e02487e0d307efdc0be5346b9f7`
- Frontend: `sha256:89a74d60eed20c220af7c9f9c08fb73e89d03023d21225d8b2288edc7eb0ca17`
- Skill Runner: `sha256:08cac524b5a411eec2b7e0d6d8cfa265adb78427b63d64297e77a4b728a86e38`
- Workspace Preview: `sha256:8b0de72d64704baa1c16343f706aba0d204d9fb477a12bbc1f3933584cf54921`

## Required continuation

1. Merge and deploy stage 1 so the existing staging database moves from `0073` through `0074` to `0075` while the full historical chain is still present.
2. Verify the staging revision, nine service health, administrator login, employee login and employee CRUD regression.
3. Apply the reviewed single-baseline commit only after staging is confirmed at `0075`; rebuild and redeploy without database DDL.
4. Complete the real `root` and `zhangsan` browser/API/permission matrix, clean reversible E2E records and append final deployment evidence.

Do not deploy the sole-baseline source to a staging database still at `0073`.
