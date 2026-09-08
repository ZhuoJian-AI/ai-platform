# Runtime synchronization session-stability hotfix

## Scope

- Deploy source merge `fb6642381885efce378804d9c00953953da371af`.
- Update only the five services that share the backend application image.
- Leave the frontend, Nginx, database schema, domains, OSS configuration and subsystem deployments unchanged.

## Immutable artifacts

- Backend source archive SHA-256: `bc6ce5fe750841fdd98584b6d2d50e84c04498190c5b3d1c41ca04a85445e4b5`.
- Backend image: `127.0.0.1:5000/zhuojian/ai-platform-backend-app@sha256:0d2e00c8a07b1c586c6f289033f48ea2cba76cfb88e65e34a735389754485390`.
- Image OCI revision: `fb6642381885efce378804d9c00953953da371af`.
- Previous backend image: `sha256:7113e95993ef620eb3c40ed447e3509d57691a5bfe0fc7a6ac6593779961ff08`.
- Frontend remains: `sha256:dbb557d65d1a27bfccfe334aee2dc08b79c21a4da8f7a0c858f440bf9ff33cda`.

## Verification before deployment

- Repeated identical Runtime synchronization preserves the current employee `auth_epoch`.
- A real authorization change still increments the affected employees' `auth_epoch`.
- Runtime, enterprise-application and role-lifecycle suites: `40 passed`.
- Full backend suite: `577 passed`.
- Image import and Ruff checks passed against the immutable image.
- No database migration is included; rollback is image-only.
