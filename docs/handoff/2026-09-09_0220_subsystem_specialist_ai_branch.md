# Subsystem specialist AI branch handoff

## Scope

- Add a platform-owned specialist AI path for embedded v2.5 subsystems without restoring retired DSH or extension execution chains.
- Support `vision.ocr`, `vision.compare`, `vision.classify`, `speech.transcribe`, `text.extract` and `business.predict` as reviewable drafts.
- Keep provider credentials, routing, quota, DLP, temporary input storage, result validation and authorization in the SaaS host.
- Do not modify or deploy any business subsystem.

## Changed behavior

- Manifest ingestion accepts a closed `platformAiCapability` declaration only for AI-enabled query Actions with a real closed result Schema and mandatory human confirmation.
- Employee-authenticated `/api/v1/subsystem-ai/runs` creates an idempotent asynchronous job after rechecking organization, application, module, page, Action and current role grants.
- Inputs are bounded, inspected and temporarily stored through the existing storage gateway; terminal input objects are deleted on success, failure or cancellation.
- The multimodal worker rechecks `auth_epoch` and Action access before and after provider execution, uses a strict structured-result tool plus one bounded correction attempt, validates the result Schema and returns only a draft, confidence, warnings and provenance.
- The embedded host Bridge validates child window, origin, launch nonce and all resource identifiers; it polls the authenticated SaaS endpoint and returns bound accepted/progress/result events. The subsystem still requires an explicit human confirmation followed by a normal business Action.

## Verification

- Frontend: `npm run test:subsystem-bridge` passed.
- Frontend: `npm run build` passed (`vite`, 4582 modules; only the repository's existing large-chunk warning).
- Backend: Python 3.14 `compileall` passed for `app` and the new tests.
- Backend: targeted Ruff passed for every changed Python module and the new test.
- Backend: the three new isolated contract/worker tests passed when invoked without the repository-wide autouse database fixture.
- Repository `git diff --check` passed.

## Test environment limitation

- The normal backend Pytest suite could not start because its mandatory local PostgreSQL test service at `localhost:5434` was not running (`ConnectionRefusedError`). This happened during fixture setup before any assertion. Docker was unavailable in this environment.

## Release state and coordination

- This branch has not been merged and no staging deployment or database migration was triggered.
- A separate AI Platform simplification and dual-end E2E task announced that it is entering the modification phase. That task must integrate or cherry-pick this branch after resolving any overlap, rerun PostgreSQL-backed tests, and own the next staging merge/deployment.
- Real employee browser E2E remains pending because the current production subsystems do not yet declare the new optional capability and this task was explicitly prohibited from modifying them.

## Risks and decisions

- The feature flag defaults to enabled only for the `alphabet` allowlist, but the path is inert until a v2.5 Manifest declares an allowed specialist capability and the employee is granted the exact Action.
- Model output can never commit business data. A subsystem must present and allow correction of the draft, then use its normal confirmed Action and existing audit/version controls.
- Temporary storage cleanup failures remain marked in job parameters for operational detection; no provider key or long-lived input URL is returned to the child frame.
