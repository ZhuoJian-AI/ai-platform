# AI Platform agent guide

## Start here

- Read this file, `TASKS.md`, and the latest entries in `docs/handoff/` before editing.
- Use one Git worktree per agent. Never work directly on `main`.
- Claim a task in `TASKS.md` and commit the claim before changing product code.

## Commands

```text
make setup
make migrate
make test
make lint
cd frontend && npm ci
cd frontend && npm run build
cd frontend && npm run lint
docker compose -f docker-compose.coolify.yml config
```

Run focused backend tests from `llm_router/backend` with `pytest tests/<file>.py -q`.
Run frontend contract checks with the relevant `npm run test:*` script.

## Architecture

- `llm_router/backend/app/`: shared FastAPI backend, authentication, permissions, model routing, agents, workspaces and integrations.
- `frontend/src/`: React/TypeScript administrator and employee interfaces.
- `skill_runner/`: isolated execution service for user-uploaded Skills and trusted file tools.
- `docker-compose.coolify.yml`: Registry-first staging deployment manifest.
- `llm_router/backend/alembic/versions/`: the single database migration chain.

## Hard boundaries

- SaaS owns identity, roles, authorization, model routing, workspaces and audited integration calls.
- Business records, workflow and business to-dos remain in registered subsystems.
- Never expose secrets, database ports, Docker APIs or unrestricted server paths.
- Permission changes require denial tests as well as happy-path tests.
- Database changes use expand/migrate/contract sequencing; verify the previous image remains compatible during rollout.
- Do not edit image digests until the source commit is tested and the registry has returned the new digest.
- Do not commit `.env`, tokens, keys, database backups, generated artifacts or local tool settings.

## Standard change flow

1. Fetch the latest `origin/main` and create a dedicated branch/worktree.
2. Inspect the affected call chain and migrations before editing.
3. Make the smallest coherent change and add focused tests.
4. Run `git diff --check`, focused tests, backend lint and the frontend build as applicable.
5. Write one handoff file under `docs/handoff/` and remove the completed task block from `TASKS.md`.
6. Stage explicit files, review the staged diff, and commit with a conventional message plus `Co-Authored-By: Codex <codex@openai.com>`.
7. Rebase or merge the latest `origin/main` without force-pushing, rerun tests, then publish.

## Collaboration

- Migration chain, authentication, permissions and CI are single-flight areas owned by `@ZhuoJian-AI/developers`.
- Preserve unrelated user changes. Never stash, discard, reset or clean another contributor's work.
- A handoff must record the task, changed behavior, exact verification commands/results, remaining work, risks and decisions.
