# Business intent query compatibility release

## Scope

- Deploy source merge `a5dfb0daf9d1d5f74b7fef0c24e0ba853e55615c` for the business-intent `groupBy` compatibility fix.
- Update only the five services that share the backend application image.
- Leave frontend/Nginx, database, domains, Skill and registered subsystems unchanged.

## Immutable artifact

- Source archive: exact `git archive origin/main`.
- Source archive SHA-256: `acb360319b9bc3a49b0e5fb272d51b5b35b02f867c5c13fac5d48ec59ae0670d`.
- Backend image: `127.0.0.1:5000/zhuojian/ai-platform-backend-app@sha256:9b9509f132cddb8c68023ff20a244a5939f092dd4b9ab83da96db089cd51aa1c`.
- OCI revision: `a5dfb0daf9d1d5f74b7fef0c24e0ba853e55615c`.
- Previous backend image: `sha256:0805b83d96d491daa16411c2dac41fc6184fe3c34e59c3c747b91f2492c243d8`.

## Pre-deploy verification

- Image test suite: 50 focused tests passed.
- Source test suite: 50 focused tests passed.
- Ruff passed for the changed service and tests.
- The compose manifest remains registry-first and has no source bind mount or build directive.

## Deployment and acceptance

- Deployment status, service health, digest/revision checks and Zhangsan browser acceptance will be appended after Coolify completes.
- Rollback is image-only to the previous digest; no database rollback is required.
