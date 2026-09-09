# AI Platform agent guide

## Product definition

AI Platform is the enterprise AI control plane:

```text
企业身份与角色鉴权
+ 模型能力网关
+ 统一 AI Assistant Core
+ 工作空间与文件交付
+ 企业子系统接入与业务 Action 执行
```

It is not a standalone business application, a RAG product, or a plugin marketplace. Business records, workflows, forms and business to-dos remain in registered subsystems.

The retained product capabilities are:

- Enterprise, department, employee, role and permission administration.
- Model-provider and deployment management for LLM, vision/OCR, image generation, ASR, TTS, video and future model capabilities.
- One user-visible AI assistant backed by one Assistant Core, with global orchestration and current-page execution modes.
- Workspaces, file versions, controlled document/media tools, previews, downloads and trustworthy Artifact delivery.
- Subsystem Runtime, Manifest, Action, Event, SSO, Bridge and ECS Publisher integration.
- Conversations, tasks, bounded execution events, usage accounting, audit, security and lightweight operational monitoring.

The employee product surface stays small: the unified assistant, workspaces, authorized enterprise applications, conversations/tasks, files and optional lightweight text-persona presets. A text persona is configuration on the shared Assistant Core, never a separate runtime or a private tool stack.

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

## Authorization source of truth

- Authentication establishes which employee is present. Authorization is derived only from that employee's active role assignments and the permissions carried by those roles.
- An employee may hold multiple roles; effective page, Action and workspace permissions are the union of those roles. Action permission and its data scope must remain paired to the role that grants them so scopes from different roles cannot be recombined into a wider privilege.
- Department membership is organizational metadata. It must not implicitly grant SaaS pages, subsystem pages, Actions, business data or department-workspace access.
- Do not implement direct per-user business grants, department-based authorization fallbacks or special username checks. User identity is used for login/session binding, audit attribution, ownership and the employee's personal workspace, not as a substitute permission source.
- Enterprise administrator `*` and platform-super-administrator authority are role permissions, not hidden user or department exceptions. The permission UI must display their computed effective role permissions accurately.
- SaaS endpoints, workspace APIs, Assistant tools, Manifest Action selection, SSO claims, Bridge context and subsystem authorization must all consume the same role-derived permission result. A subsystem must not infer access from department or user identity.
- Role assignment or role-permission changes must advance `auth_epoch`; the next request must recompute effective permissions and reject stale claims or cached page state.

## Assistant execution model

The LLM is the reasoning and orchestration brain. Keep the system prompt short: understand the user's goal from the current context, use tools for real data or effects, correct tool errors, and never claim success without a verified result. Do not encode every workflow, navigation decision or presentation rule in system-prompt prose, and do not require a perfect, oversized intent object before the model may use an authorized tool.

The user experiences one continuous assistant and one conversation. The backend switches between two modes of the same Assistant Core:

- **Global orchestration mode（总业务 AI）** knows the employee's role-authorized enterprise capability directory, uses shared platform tools, locates the correct application/module/page and hands off the unfinished goal. It does not preload every subsystem CRUD tool.
- **Current-page execution mode（页面业务 AI）** receives the verified application/module/page/object context and loads only that page's role-authorized Manifest Actions plus the needed shared platform tools.

The modes share the Task/conversation, concise history, recognized entities, referenced files, Artifacts, completed steps and remaining goal. They do not share an unbounded prompt or every tool. A handoff must preserve the user's original request so the page assistant never asks the user to repeat it.

The required tool loop is:

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

Navigation is a tool, not a mandatory step. Complete safe background work in the conversation and offer an “打开查看” action; navigate when the user requests it or when page interaction/visual confirmation is genuinely required. Show verifiable progress, confirmation cards, before/after values, tool receipts and Artifacts to the user, but never expose private chain-of-thought.

## Model and tool capabilities

- The LLM remains the main brain. Vision/OCR, image generation, ASR, TTS, video and other non-LLM model deployments are exposed to it as narrowly scoped, audited tools.
- Use one capability registry shared by the global assistant and page assistant. Load only the capability group needed for the current turn instead of exposing a permanent large tool list.
- Shared platform tools include workspace search/read/versioned write, controlled Excel/Word/PPT/PDF/Markdown/TXT processing, preview/download, Web, media understanding/generation and Artifact delivery.
- Business tools come only from the current role-authorized Manifest Actions. Platform tools and subsystem Actions remain distinguishable in provenance and auditing.
- Workspace files may be inspected directly through file tools when selected or referenced. Do not rebuild this as RAG or silently index all workspace content.

## Subsystem integration boundary

- A subsystem owns its business UI, records, rules, forms, workflows, attachments, page semantics and real CRUD implementation.
- SaaS owns identity, role-derived authorization, model providers, the LLM brain, tool orchestration, confirmation UI, navigation/handoff, shared model and file capabilities, workspaces, AI-generated Artifacts, audit and usage accounting.
- `Manifest.aiSemantics` supplies a compact application/module/page capability directory for discovery and navigation. Exact execution comes from closed Action schemas and verified Action results, not from descriptions alone.
- The external `aifabei-subsystem-builder` Codex Skill defines this integration contract. It is outside this repository and must never be conflated with the retired in-product user Skill feature.

## Retired product paths

Do not restore, retain through compatibility aliases, or silently reintroduce these removed product paths without an explicit new product decision:

- Knowledge-base/RAG products, vector indexing, embedding and reranker model capabilities.
- User Skill upload, installation and execution, arbitrary-code Skill Runner and per-agent Skill binding.
- DSH Runtime, market, external extensions and extension builder.
- Connector, Tool Endpoint, Data Interface/Data System and application tool-binding abstractions superseded by Manifest Actions.
- Ontology, Judge, MCP/OAuth Skill Pack, Team and ScopeManager products.
- Legacy module publisher and online Office collaborative editing.
- Separate personal-assistant and business-assistant execution engines. They are modes of the one Assistant Core, not independent products.

## Hard boundaries

- SaaS owns identity, role-derived authorization, model routing, workspaces and audited integration calls.
- Business records, workflows and business to-dos remain in registered subsystems.
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
