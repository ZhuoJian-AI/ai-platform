# Business intent JSON compatibility release

## Scope

- Deploy source merge `545db51d89af6a1bfe40f896d963d4c0c6763916`.
- Update only the five services sharing the backend application image.
- Leave frontend/Nginx, database, domains, Skill and registered subsystems unchanged.

## Immutable artifact

- Source archive: exact `git archive origin/main`.
- Source archive SHA-256: `59049466c9a2f5bd1444e7790cd60c4fc6b013814bfca30c11d86821996a877f`.
- Backend image: `127.0.0.1:5000/zhuojian/ai-platform-backend-app@sha256:ea53404167295cb9150a8c23c370062bddf5fadee77f5bdca83d5241a4fd5cb9`.
- OCI revision: `545db51d89af6a1bfe40f896d963d4c0c6763916`.
- Previous backend image: `sha256:9b9509f132cddb8c68023ff20a244a5939f092dd4b9ab83da96db089cd51aa1c`.

## Verification

- Source and image focused suites: 51 passed.
- Ruff and diff checks passed.
- Deployment validation and Zhangsan browser acceptance will be recorded after Coolify finishes.
- Rollback is image-only; this release has no database migration.
