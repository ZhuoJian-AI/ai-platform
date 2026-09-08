# Runtime auto-release and system developer deployment

## Scope

- Deploy product merge `0d2d507d5b1bfc399d142b1c805e986dbba83913`.
- Update the five services sharing the backend application image and the frontend service.
- Leave domains, Runtime credentials, OSS configuration and registered subsystem deployments unchanged.
- Apply the additive `0070_runtime_auto_release` database migration during backend startup.

## Immutable artifacts

- Backend source archive SHA-256: `c2c01a1864da4e9caa65e1cfdbff5afb1268ac736a4700a17f5784a430630a7a`.
- Frontend source archive SHA-256: `ed62c556d101eb6cd23e333f38d2611f090cf128c34ede3772fe4ccb5a5ba1ce`.
- Backend image: `127.0.0.1:5000/zhuojian/ai-platform-backend-app@sha256:7113e95993ef620eb3c40ed447e3509d57691a5bfe0fc7a6ac6593779961ff08`.
- Frontend image: `127.0.0.1:5000/zhuojian/ai-platform-frontend-app@sha256:dbb557d65d1a27bfccfe334aee2dc08b79c21a4da8f7a0c858f440bf9ff33cda`.
- Both images carry OCI revision `0d2d507d5b1bfc399d142b1c805e986dbba83913`.
- Previous backend image: `sha256:b25c740d6bad7fe65f72753945e41515082e5c3e91c2be02297be4571aa81f9e`.
- Previous frontend image: `sha256:db9b8b9bea6d7dfd5f3d46666e8c567ec203729018a2675a5f55426e9e782c85`.

## Pre-deployment verification

- Full backend suite: `577 passed`.
- Focused Runtime, application and role suites: `74 passed`; image-import, Alembic head and Ruff checks passed.
- Frontend production build and bridge/session scripts passed; the final image serves its SPA entry point successfully.
- Registry-first Compose validation passed for all 13 services, with no source-build service, forbidden database publication or repository bind mount.
- Live required-environment validation passed without exposing secret values.
- Current database revision is `0069_retire_team_scope`.
- A pre-`0070` PostgreSQL custom-format backup was created, SHA-256 checked and parsed by `pg_restore -l`; the backup file is mode `0600`.
- Rollback is image-only. The additive migration will not be rolled back.

## Pending completion checks

- Coolify deployment ID and all-service health.
- Running digest and OCI revision verification.
- Cross-service token fingerprint verification.
- Public health, database revision and real employee browser acceptance.
