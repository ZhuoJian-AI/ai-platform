# Assistant tool-loop guide handoff

## Scope

- Branch: `docs/assistant-tool-loop-20260909`
- Base: `7658fb1`
- Documentation-only change; no product code, database, Skill, deployment or server state changed.

## Result

- Added the required LLM-led assistant execution loop to the project `AGENTS.md`.
- Clarified that understanding, tool selection and bounded correction belong to the LLM loop.
- Clarified that identity, authorization, Action targets, schemas, side effects, idempotency and Artifact truth remain strict SaaS execution boundaries.
- Explicitly prohibited presenting model/protocol validation failures as user ambiguity.

## Verification

- `git diff --check`: passed.
- Reviewed the complete `AGENTS.md` diff.
