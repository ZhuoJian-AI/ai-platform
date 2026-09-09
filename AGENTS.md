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
- `tool_executor/`: isolated execution service for fixed, reviewed platform file tools; it never runs user code.
- `docker-compose.coolify.yml`: Registry-first staging deployment manifest.
- `llm_router/backend/alembic/versions/`: the single database migration chain.

## Assistant execution model

The LLM is the reasoning and orchestration brain. Do not require a perfect, oversized intent object before the model may use an authorized tool. The required loop is:

```text
用户自然表达
→ LLM 主脑结合当前页面理解目标
→ 从当前授权工具中选择工具
→ SaaS 校验工具参数
   ├─ 正确：执行
   └─ 错误：把“哪里错、应该怎么填”返回给 LLM
→ LLM 自动修正并再次调用
→ 获得结果后继续决定是否调用下一个工具
→ 最终回答用户
```

- Allow a bounded reasoning/tool loop and one or two corrective retries for protocol, parameter and tool errors. Return actionable structured errors to the LLM instead of immediately ending the turn.
- Use current page context, conversation history and the authorized tool set to resolve ordinary business shorthand. Ask the user only when a required business fact is genuinely missing or multiple materially different choices remain.
- A model/protocol validation failure is a platform failure, not evidence that the user's request is ambiguous. Never translate it into a generic clarification message.
- Keep strict enforcement at the execution boundary: identity and permission intersection, application/module/page/Action target, closed input Schema, confirmation for side effects, idempotency, output validation and trustworthy Artifact delivery.
- The LLM may reason, select, retry and compose tools, but it may never invent permissions, credentials, target URLs, successful tool results or completed files.

## Hard boundaries

- SaaS owns identity, roles, authorization, model routing, workspaces and audited integration calls.
- The external `aifabei-subsystem-builder` Codex Skill is a subsystem contract and is outside this repository; never conflate it with the retired in-product user Skill feature.
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
