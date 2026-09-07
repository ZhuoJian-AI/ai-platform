# Business intent per-call thinking release

## Scope

- Deploy source merge `45b3d269778c9c48fbbbe2c44dbd3102e6f3e590`.
- Update only the five services sharing the backend application image.
- Leave frontend/Nginx, database, domains, Skill and registered subsystems unchanged.

## Immutable artifact

- Exact source archive SHA-256: `a92fa0c57c1906c626e91e1556c54bce80577d57aa2eb13d314b034073a7ff68`.
- Backend image: `127.0.0.1:5000/zhuojian/ai-platform-backend-app@sha256:c94629022e1f0135cf642fc14573034170564c1291598396e4c9a3cbc3ca21b9`.
- OCI revision: `45b3d269778c9c48fbbbe2c44dbd3102e6f3e590`.
- Previous backend image: `sha256:ea53404167295cb9150a8c23c370062bddf5fadee77f5bdca83d5241a4fd5cb9`.

## Verification

- Source and image focused suites: 52 passed.
- Ruff, import and diff checks passed.
- Deployment validation and Zhangsan browser acceptance will be recorded after Coolify finishes.
- Rollback is image-only; this release has no database migration.
