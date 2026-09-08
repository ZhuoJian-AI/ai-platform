# Active tasks

## PLAT-RUNTIME-AUTO-RELEASE-006 (@codex-runtime-release)

- Replace per-release administrator approval with validated, atomic Runtime-managed manifest activation while preserving the last healthy release.
- Add the immutable organization-scoped system developer role and safe inheritance for existing-app additions, including explicit administrator deny persistence.
- Acceptance: valid releases auto-activate, invalid or stale releases leave the active catalog untouched, the system developer sees all same-organization Runtime apps without SaaS administration privileges, and real employee regression tests pass.
