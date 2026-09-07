# Business assistant semantic orchestration handoff

## Owner and task

- Owner: Codex
- Task: `PLAT-BUSINESS-SEMANTICS-001`

## Changed behavior

- Added a server-owned business-turn envelope and strict, schema-validated intent classification for semantic-enabled subsystem pages.
- Dynamically narrows each turn to the current page Action, one authorized related-page read Action, or the required workspace file capability.
- Persists page, entity, filter, tool, artifact and approval references without replaying unbounded business rows into later prompts.
- Added application-scoped conversation discovery, lazy new-conversation drafts, URL restoration, soft deletion and global-history routing back into the owning application.
- Added deterministic completion guards for live queries, mutations and workspace artifacts, plus trace and golden-set scoring helpers.
- Preserved SSE replay, trusted artifacts, versioned workspace files and silent iframe refresh.

## Verification

- `pytest test_dsh_approval.py test_business_assistant_orchestration.py test_business_assistant_evaluation.py test_dsh_policy.py -q`: 46 passed.
- Focused Ruff check for changed backend and tests: passed.
- `npm run test:subsystem-bridge`: passed.
- `npm run build`: passed (existing chunk-size warnings only).
- `git diff --check`: passed.

## Remaining release work

- Rebase onto the latest `origin/main`, publish the tested images, deploy staging and run the authenticated Zhangsan browser scenarios.
- Local database-backed tests require PostgreSQL and were not used as a substitute for staging end-to-end verification.

## Decisions and risks

- No database schema was added; application ownership remains in `Task.config.application_id`.
- Existing applications without `aiSemantics` continue through the legacy route. The semantic route activates only after an updated Manifest is synchronized.
- Golden-set thresholds are enforced by the scoring helper; production model quality still requires the staged shadow/real-account run.
