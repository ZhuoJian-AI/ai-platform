# Business assistant orchestration staging completion

## Completed scope

- Structured `BusinessTurnEnvelope` and `BusinessTurnIntent` routing with server-side validation.
- Model-based query rewriting, current/related-page semantic routing, bounded authorized tool assembly, and deterministic completion rules.
- Application-scoped multi-conversation history, URL restoration, canonical page labels, and artifact restoration.
- DeepSeek/OpenAI-compatible provider handling: forced-tool compatibility retry, validated JSON compatibility mode, per-controller thinking disabled, scalar `groupBy` normalization, and empty optional `timeRange` normalization.
- Existing trusted workspace artifacts, SSE replay, and silent iframe refresh behavior preserved.

## Git and immutable release

- Final product source merge: `1464f59d99f36f5a555b212f78708aa3bbb9f667` (PR #46).
- Final deployment manifest merge: `59176e90a3fca969a002eadaae32d1ba7608f587` (PR #47).
- Exact source archive SHA-256: `15800b2984a9ca5c786170b56824b7641495ce0d532abed7fae9ca5f7018567f`.
- Deployed backend image digest: `sha256:b25c740d6bad7fe65f72753945e41515082e5c3e91c2be02297be4571aa81f9e`.
- OCI source revision: `1464f59d99f36f5a555b212f78708aa3bbb9f667`.
- Coolify deployment: `r2ihneakaqxwwpn1wuetsa7a` (success). An earlier attempt `lepj2dwh0vygap8vh3octjhp` failed before build because the Coolify host timed out while cloning GitHub; the retry used the same manifest and succeeded.

## Automated verification

- Focused orchestration, workspace presentation, tool-choice, and DSH bridge suites: `53 passed` in source and final image.
- Ruff and diff checks passed.
- Central Registry-first Compose validator passed against `origin/main`; no source-build service, forbidden database publication, floating base image, or repository bind mount was found.
- Live environment validator passed without exposing secret values; DSH Runtime, Skill Runner, and Extension Builder caller/server tokens match.
- All 13 Coolify services are healthy; public `GET /health` returns `200 {"status":"ok"}`.
- All five backend-image services run the pinned digest above and report the expected OCI revision.

## Zhangsan real-browser acceptance

- Page explanation task `95f54a18-872d-4a37-af77-ce9686d4a9ab`: intent `explain_page`, canonical page `生产进度看板`, zero tool calls, successful semantic explanation.
- Live query task `0bdb9795-3070-4b1b-8b78-1af36f584e13`: intent `query`, one and only one successful authorized `progress_dashboard.query` Action, verified live result of four risk orders.
- Query completion retained the original iframe DOM node; observed load count remained zero.
- Excel task `57622e7f-cf69-4a06-8029-ddef1a217dc7`: intent `export_file`, one successful `business_export_to_workspace_file`, trusted workspace Artifact created in Zhangsan's personal workspace.
- Artifact download returned HTTP 200, OOXML/XLSX MIME, ZIP magic `PK`, 6,854 bytes, and SHA-256 `ca6e17dd7d3af1addc03bd48d03b48be45a8fdf4206b9a091aa25b82ca298898`, matching persisted provenance.
- Excel completion also retained the original iframe DOM node with zero reloads.
- Conversation URL survived a full reload; messages, file card, preview/download controls and canonical page label were restored. The current application history lists and switches among multiple conversations.

## Related contract and subsystem state

- Skill stable main is `b60679a` (`1.0.6`); local auto-update reports current and its full suite reports `167 passed, 41 skipped`.
- Garment subsystem GitHub main and deployed source are both `606548ed6392bf19d35a382c8b61f59c73398b1d`.
- Garment deployed image digest is `sha256:ba5eb745759023005c004ce0b69a79c1708d86476601525225f91e00932a2dcd`; container and `/health` are healthy on `8.218.208.205`.
- The runtime doctor reports healthy storage gateway/OSS mode, adequate disk, and uploads enabled.

## Boundaries and remaining notes

- No database migration, backup, domain, frontend/Nginx, administrator authentication, billing, Skill, or garment code change was included in the final SaaS compatibility hotfix.
- Historical conversations created before page-context persistence can still display `未记录页面`; new and recently migrated conversations use canonical page names. No destructive backfill was attempted.
- No old garment server was connected or modified.
