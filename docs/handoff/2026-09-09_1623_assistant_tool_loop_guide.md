# Assistant tool-loop guide handoff

## Scope

- Branch: `docs/assistant-tool-loop-20260909`
- Base: `7658fb1`
- Documentation-only change; no product code, database, Skill, deployment or server state changed.

## Result

- Added the required LLM-led assistant execution loop to the project `AGENTS.md`.
- Defined the current slim product boundary, one user-visible assistant with global-orchestration and page-execution modes, the model/tool capability registry and subsystem/SaaS ownership split.
- Established role assignments as the sole business-authorization source; departments and user identity cannot create implicit business access.
- Recorded RAG, embedding/reranking, in-product user Skills, DSH and the other retired product paths as features that must not be silently restored.
- Clarified that understanding, tool selection and bounded correction belong to the LLM loop.
- Clarified that identity, authorization, Action targets, schemas, side effects, idempotency and Artifact truth remain strict SaaS execution boundaries.
- Explicitly prohibited presenting model/protocol validation failures as user ambiguity.

## Verification

- `git diff --check`: passed.
- Reviewed the complete `AGENTS.md` diff.
