# Business intent empty range release

## Scope

- Deploy source merge `1464f59d99f36f5a555b212f78708aa3bbb9f667`.
- Update only the five services sharing the backend application image.
- Leave frontend/Nginx, database, domains, Skill and registered subsystems unchanged.

## Immutable artifact

- Exact source archive SHA-256: `15800b2984a9ca5c786170b56824b7641495ce0d532abed7fae9ca5f7018567f`.
- Backend image: `127.0.0.1:5000/zhuojian/ai-platform-backend-app@sha256:b25c740d6bad7fe65f72753945e41515082e5c3e91c2be02297be4571aa81f9e`.
- OCI revision: `1464f59d99f36f5a555b212f78708aa3bbb9f667`.
- Previous backend image: `sha256:c94629022e1f0135cf642fc14573034170564c1291598396e4c9a3cbc3ca21b9`.

## Verification

- Source and image focused suites: 53 passed.
- Ruff and diff checks passed.
- Deployment validation and Zhangsan browser acceptance will be recorded after Coolify finishes.
- Rollback is image-only; this release has no database migration.
