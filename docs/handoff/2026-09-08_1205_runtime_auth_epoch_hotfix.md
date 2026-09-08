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

## Deployment completion

- Deployment-manifest merge: `d34cd182fa66084aac46f42f012513de7ef545b9`.
- Coolify deployment: `x1ssj56nieuzajxniprjx90p`, completed successfully.
- All 13 services are healthy. `backend`, `workspace-parser`, `office-edit-reconcile`, `storage-lifecycle` and `multimodal-worker` all run `sha256:0d2e00c8a07b1c586c6f289033f48ea2cba76cfb88e65e34a735389754485390` with OCI revision `fb6642381885efce378804d9c00953953da371af`.
- The frontend remained on `sha256:dbb557d65d1a27bfccfe334aee2dc08b79c21a4da8f7a0c858f440bf9ff33cda`. Nginx, domains, OSS configuration and cross-service credentials were not changed.
- The public health endpoint returns HTTP 200. The database remains at `0070_runtime_auto_release`; no new migration was applied.

## Production acceptance

- The built-in employee role is present as `系统研发者` / `zj-runtime-developer`, with `system_key=runtime_developer`, `data_scope=all`, built-in and active. Its Runtime-managed application grant is present, while no employee remains bound after the temporary test assignment was removed.
- The registered production-collaboration application is active and not administrator-disabled. Integration and Runtime release state are both `healthy`; Manifest review state is `approved`; the candidate Manifest is empty; requested and successful commits both equal `606548ed6392bf19d35a382c8b61f59c73398b1d` under contract `2.5`.
- A real `zhangsan` employee session using only the temporary system-developer role launched the application twice with HTTP 200. The subsystem session and state endpoints returned HTTP 200.
- The employee asked `当前有多少风险订单？`; the assistant returned the four live risk orders from the current `progress_dashboard` page. The query completed without rebuilding the embedded iframe.
- The employee token and database both stayed at `auth_epoch=110` through subsequent background synchronization and the completed assistant run. This verifies that an identical Runtime sync no longer logs the employee out.
- After acceptance, `zhangsan` was restored to the original `总经理` and `production01` roles only; the resulting authorization change advanced the epoch to `111` as expected.
- The subsystem on `8.218.208.205` was checked read-only and was not redeployed: its container is healthy on image digest `sha256:ba5eb745759023005c004ce0b69a79c1708d86476601525225f91e00932a2dcd`, and public `/health` reports contract `2.5` with the OSS gateway.
- The local Alphabet builder Skill updated through its signed stable updater from `1.0.6` to `1.0.7`; the published Skill release tests remain `170 passed, 41 skipped`.

## Remaining work

- No release blocker remains. Invalid-candidate preservation, latest-wins activation, managed-role immutability, inherited-grant ceilings, administrator denials and event-route non-creation are covered by the feature test suites; this completion pass did not mutate production authorization or event routes solely to repeat destructive denial cases.
