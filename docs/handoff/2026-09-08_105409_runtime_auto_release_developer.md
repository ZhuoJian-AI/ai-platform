# Runtime auto release and system developer handoff

## Task

- Replace per-release administrator approval for Runtime-managed systems with validated automatic activation.
- Add an immutable organization-scoped system developer role and bounded permission inheritance for existing Runtime applications.
- Preserve explicit administrator application, Action, page and module stops across later Manifest synchronization.

## Changed behavior

- A valid latest Runtime candidate becomes active after complete Manifest validation; an invalid or stale candidate cannot replace the last healthy active release.
- Every organization has one managed `runtime_developer` role with visible code `zj-runtime-developer`. Administrators may only bind or unbind employees from it.
- The role receives all business modules, pages and Actions of same-organization Runtime-managed applications, without SaaS administration, model-key or workspace-administration permissions.
- Existing business-role grants inherit newly declared resources only within their previous permission ceiling. Explicit removals are retained as denials; removed Manifest resources are pruned.
- New Runtime applications grant only the system developer automatically. Event declarations do not create routes.
- Administrators can persistently stop a whole Runtime application or an individual Action; later Runtime synchronization cannot reopen it.

## Verification

- Backend focused/expanded Runtime and authorization tests: `74 passed`.
- Backend complete suite: `577 passed in 448.10s`.
- Latest focused suite after boundary fixes: `58 passed`.
- Alembic empty-database upgrade to `0070_runtime_auto_release`, downgrade/upgrade cycle and seeded upgrade from the previous revision all passed on PostgreSQL.
- Frontend production build passed.
- `npm run test:subsystem-bridge`: passed.
- `npm run test:business-conversation`: passed.
- `npm run test:admin-session`: passed.
- `git diff --check`: passed.

## Decisions and risks

- Candidate and active release state remain separate; employee access uses the last healthy commit while a later candidate is verifying or failed.
- Database rollback is not part of deployment recovery. A failed application rollout must switch back to the previous image digest while retaining migration `0070`.
- The administrator denial model is intentionally scoped to Runtime-managed application grants; manually onboarded legacy applications keep their existing review workflow.

## Remaining work

- Merge the feature branch after integrating the latest `origin/main`.
- Build Registry-first images, back up the staging database, deploy the migration and services, then run real administrator and employee browser regression tests.
