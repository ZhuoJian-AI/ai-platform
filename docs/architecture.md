# ai-platform 架构总览（按代码写，非按 README 写）

> 基线：`main@3435cb8`（2026-09-03）。所有结论都来自打开过的文件，引用格式 `路径:行` 或 `路径::函数`。
> README 说"四个子系统"且 `tool_connector/ app_monitor/ agent_platform/` 各有目录——实际这三个目录只有一个 `README.md`，全部代码都在 `llm_router/backend/app/` 一个 FastAPI 包里。

## 1. 一句话定位与五个子系统

**一个 FastAPI 后端 + 一个 React 控制台 + 四个 Docker 内部 sidecar，给企业提供「LLM 代理网关 + 终端智能体 + 工作空间文件 + 企业模块集成」，多租户按组织隔离。**

前端一级菜单（`frontend/src/App.tsx:70-200` 的 `SUBSYSTEMS`）分七组：企业与权限 / 企业设置 / 模型路由器 / 智能体平台 / 工具连接器 / 平台扩展（仅超管）/ 应用监控台。后端不按子系统分包，全部 router 汇聚在 `app/api/router.py`。

五个子系统共用的东西：
- 同一个 Postgres（pgvector）+ Redis；同一套 alembic 迁移（57 个版本，head `0057_department_sort_order`）
- 组织/部门/团队/用户/角色模型（`app/models/organization.py`、`department.py`、`team.py`、`user.py`、`role.py`）
- 三种鉴权：管理员 JWT `app/auth/admin_auth.py::require_admin`、终端用户 JWT `app/auth/user_auth.py::require_user`、代理 API Key `app/auth/api_key_auth.py::authenticate_request`
- 模型网关 `app/services/model_gateway.py`（chat / stream_chat / embed / generate_image / transcribe_audio），Agent、RAG、多模态、DSH 桥全部经它调上游
- 对象存储网关客户端 `app/services/storage_gateway_service.py`（平台不持有 OSS AccessKey，只拿签名 URL，DB 里存 `oss://` 引用）
- 前端统一 client `frontend/src/api/client.ts`（3050 行，一个 `request()` + 按领域导出的对象）

## 2. 仓库目录地图

| 路径 | 一句话 |
|---|---|
| `llm_router/backend/app/` | 唯一的后端包 `app`。README 里的 tool_connector / app_monitor / agent_platform 都在这里 |
| `app/api/` | 35 个 FastAPI router（见 §3.0 表）；`terminal.py` 2361 行是终端用户全部接口 |
| `app/services/` | 51 个 service，业务逻辑层（见 §2.1 分组） |
| `app/agents/` | 终端智能体：`graph/nodes.py`（2756 行，工具定义+执行+prompt 组装）、`dsh/runner.py`（调 DSH runtime）、`dsh/registry.py`（run_token → 上下文） |
| `app/graph/` | **另一个** LangGraph：`/v1` 代理请求流水线（权限→DLP→路由→上游→审计），与 `app/agents/graph` 无关 |
| `app/proxy/` | `/v1/messages`、`/v1/chat/completions`、`/v1/models` HTTP 入口 + 协议适配 |
| `app/dlp/` | 正则/关键词/NER/自定义规则引擎 + 流式扫描 |
| `app/routing/` | 模型别名 → provider 选择（作用域优先级 + 加权） |
| `app/workers/` | 4 个独立进程 worker（parser / preview / storage_lifecycle / multimodal） |
| `app/mcp/` | `/mcp` MCP server，把 9 个平台能力暴露给第三方 agent 终端 |
| `app/models/` | SQLAlchemy ORM，35 个文件 ~80 张表 |
| `alembic/versions/` | 57 个迁移，线性单 head |
| `tests/` | 43 个 pytest 文件，全部依赖真实 Postgres |
| `frontend/` | Vite + React + antd 控制台，管理端与终端用户端同一个 SPA |
| `dsh_runtime/` | Node 22 服务（8030）：跑 DeepSeek `@deepseek-ai/dsh-*` agent loop，vendor 目录里是 tgz |
| `skill_runner/` | Python 服务（8020）：安装/执行可执行 Skill 包（zip），沙箱容器 |
| `extension_builder/` | Node 服务（8040）：构建平台扩展（pnpm install + build） |
| `mock/` | MES/CRM/ERP 等 14 个 mock 业务系统，单网关 8010，`mock/openapi/*.json` 供连接器导入 |
| `extension-sdk/` | 扩展 manifest schema + 模板，纯文档 |
| `infra/base-images/` | 9 个依赖基础镜像 Dockerfile（backend-deps、node22-pnpm、python312-office…） |
| `docker-compose.coolify.yml` | **线上真相**：12 个服务全部 image@sha256 pin |
| `docker-compose.yml` + `.prod.yml` + `.local.yml` | 本地开发 / 旧式 build 部署（prod 域名 infra.aievolve.org.cn） |
| `COOLIFY_DEPLOYMENT.md` | staging 部署参数（只写了 staging） |
| `docs/` | 用户手册 + 本文 + `audit/` |

### 2.1 services 分组

- **组织/身份**：`organization_service`、`user_service`、`admin_service`、`role_service`（RBAC + data_scope 解析）、`scope_service`（终端用户可见资源集合）、`workspace_permission_service`（工作空间能力矩阵）
- **模型/代理**：`llm_provider_service`（凭证+deployment）、`model_gateway`、`api_key_service`、`dlp_rule_service`
- **工作空间**：`workspace_service`（文件 CRUD、upsert、版本）、`workspace_governance_service`（直传会话/版本/发布/回收站/审计/分享）、`workspace_preview_session_service`（预览路由）、`workspace_pdf_preview_service`、`workspace_preview_service`、`workspace_lifecycle`（节点↔空间配对）、`storage_gateway_service`、`storage_lifecycle_service`（保留期/物理清理/迁移）、`doc_parser`
- **智能体**：`agent_service`、`task_service`、`memory_service` + `memory_lifecycle`、`rag_service`、`judge_service`、`agent_admission`（Redis 准入）、`message_verification`（工具成功声明校验）
- **技能/工具**：`skill_store_service`（技能文件夹）、`skill_import_service`（zip 包→不可变版本）、`skill_scope_service`、`skill_runner_client`、`skills_pack_service`（给第三方终端导出 skills 包）、`connector_service`、`data_interface_service`、`ontology_store_service`、`platform_tool_registry`
- **企业模块**：`enterprise_application_service`（应用+授权）、`subsystem_integration_service`（manifest 发现 + 事件拉取）、`subsystem_action_service`（幂等动作）、`module_deployment_service` + `coolify_module_client` + `github_module_publisher_service` + `ecs_publisher_service`（租户模块发布链）
- **平台扩展**：`platform_extension_service`（导入/审核/发布/激活到 DSH）、`platform_extension_discovery`、`platform_extension_catalog`、`extension_builder_client`
- **多模态**：`multimodal_service`（图片准备）、`multimodal_audio_service`（音频 job 队列 + 音色授权）

## 3. 请求生命周期

### 3.0 路由表（`app/api/router.py`，统一前缀 `/api/v1`）

| 文件 | 主要路径 | 用途 | 守卫 |
|---|---|---|---|
| admin.py | `/auth/*` `/admins` | 管理员登录、CRUD、改密 | 无/admin |
| config.py | `/config` | 公开运行时配置（proxy_base_url） | 无 |
| organizations.py | `/organizations` | 组织 CRUD、slug 别名 | admin |
| departments.py / teams.py | `/departments` `/teams` | 部门/团队 CRUD | admin |
| users.py | `/users` | 组织内终端用户 | admin |
| roles.py | `/roles` | 角色、权限码、数据范围 | admin |
| api_keys.py | `/api-keys` | 代理 API Key（lr_sk_org/dept/team） | admin |
| llm_providers.py | `/providers` | 提供商凭证、deployment、连通测试 | admin |
| dlp_rules.py | `/dlp-rules` | DLP 规则 CRUD + 测试 | admin |
| routing_policies.py | `/routing-policies` | 模型别名路由策略 | admin |
| budget.py / audit_logs.py | `/organizations/{id}/...` | token 用量、审计查询 | admin |
| workspaces.py | `/workspaces` `/files` `/workspace-uploads` | 管理端工作空间（45 个端点） | admin |
| agents.py / agent_playground.py | `/agents` | 智能体配置、测试广场运行 | admin |
| rag.py | `/rag` | 集合/文档/分块/检索 | admin |
| agent_judge.py | `/judges` | Judge 模板 | admin |
| memory.py | `/memory` | 组织/部门/团队长期记忆 | admin |
| connectors.py | `/connectors` `/endpoints` | 连接器 + OpenAPI 导入 | admin |
| data_interfaces.py | `/data-systems` `/data-interfaces` | 数据接口页独立结构 | admin |
| skills.py / skill_packages.py | `/skills` `/skill-folders` `/skill-versions` | 技能文件夹、zip 版本 | admin/user |
| ontology.py | `/ontologies` `/ontology-files` | 本体 Markdown 文件 | admin |
| monitor.py | `/organizations/{id}/monitor/*` | 路由器/智能体/工具指标 | admin |
| multimodal.py | `/multimodal/*` | 音频 job、音色治理 | admin/user |
| enterprise_applications.py | `/applications` `/terminal/applications` | 租户业务模块 + 授权 + SSO | admin/user |
| platform_extensions.py | `/platform/extensions/*` | 扩展源/目录/发布/回滚 | super_admin |
| storage_lifecycle.py | `/platform/storage-lifecycle` | 存储生命周期总览/重试 | super_admin |
| module_publisher.py / ecs_publisher.py | `/module-publisher` `/ecs-publisher` | 租户仓库 + Coolify 发布 | 租户 key / runtime |
| dsh_internal.py | `/internal/dsh/model/stream` `/internal/dsh/tools/execute` | **DSH 回调桥**，service token | `dsh_runtime_token` |
| terminal.py | `/terminal/*`（81 个端点） | 终端用户全部功能 | `require_user` |

另有两个非 `/api/v1` 挂载：`app/proxy/router.py` 的 `/v1/*`（API Key）和 `app/main.py:120` 的 `/mcp`。

### 3.1 (a) `/v1` 代理请求

入口 `app/proxy/router.py:42-77`：`authenticate_request` 依赖解析 `lr_sk_*` key → 解析 JSON → `stream` 与否分别走 `app/graph/runner.py::stream_proxy / run_proxy`。

图拓扑在 `app/graph/builder.py:52-95`（LangGraph StateGraph，`InMemorySaver` 按 request_id 隔离）：

1. `app/graph/nodes/scope.py::resolve_permissions` — 加载 org/dept/team，调 `app/auth/permission_resolver.py::resolve_effective_permissions`：模型列表取**交集**、RPM/TPM/预算取**最小值**（`permission_resolver.py:23-100`）
2. `app/graph/nodes/dlp.py::dlp_request` — `app/dlp/scanner.py::scan_request`，规则来自组织级 `dlp_rules` 表（无全局规则，建组织时由 `organization_service.create_organization` 播种，`main.py:48-50` 注释）
3. `app/graph/nodes/routing.py::resolve_route` — `app/routing/router.py::find_provider`：作用域优先级 team > dept > org（`_scope_rank`）+ `_weighted_select` 加权
4. `app/graph/nodes/proxy.py::proxy_upstream` — httpx 字节透传；流式在节点内联做响应 DLP（`app/dlp/stream_filter.py::filter_stream_with_dlp`，缓冲窗 `settings.dlp_stream_buffer_window=4096`）
5. 非流式经 `dlp_response`；所有分支收口 `app/graph/nodes/audit.py::write_audit`（`audit_logs` + `budget_usage`，token 由 `app/proxy/usage.py` 抽取）

协议转换在 `app/proxy/response_converter.py`（anthropic↔openai）。错误由 `app/graph/nodes/errors.py::build_error` 格式化。

### 3.2 (b) 终端对话一轮

1. 前端 `frontend/src/pages/terminal/Terminal.tsx` POST `/api/v1/terminal/tasks/{id}/run`（`stream=true`）；刷新/重连走 GET `/tasks/{id}/stream`（`client.ts:2576`），两者共用同一个 SSE 解析循环（`Terminal.tsx:648,768`）
2. `app/api/terminal.py:680::run_task_endpoint`：校验任务归属、强制 `workspace_id` 收敛到个人空间（:693-703）、企业模块 page_context 校验、模型必须在 `scope_service.list_available_models_for_user` 范围内（:747-750）、附件与技能可见性校验 → `app/agents/dsh/runner.py::stream_general_agent`
3. `runner.py:465::stream_general_agent`：按 task_id 在 `app/agents/graph/run_registry` 取/建 handle，起后台 `_run_bg`，立即返回 `sse_replay_and_tail(handle)`——SSE 是"回放缓冲 + 尾随"，后台任务与 HTTP 连接解耦
4. `_run_bg` → `_prepare`（:173）：`nodes.load_config` → `load_memory` → `prepare_dsh_turn`（`nodes.py:2223`，组装 system prompt、工具列表、memory_context、技能目录），把上下文注册进 `dsh/registry.py::register` 换一个 15 分钟 `run_token`
5. `_admitted_run`（:310）经 `agent_admission`（Redis 全局 12 / 每用户 2 并发，`config.py:37-42`）拿许可 → `_consume_dsh`（:188）POST `dsh_runtime/src/server.ts` 的 `/v1/runs`，NDJSON 逐行读事件
6. DSH runtime 内部：`dsh_runtime/src/runtime.ts::DshRuntime.run` 跑 `@deepseek-ai/dsh-agent-loop`；**模型调用**经 `platform.ts::PlatformLlmAdapter.stream` 回调 backend `/api/v1/internal/dsh/model/stream`（`app/api/dsh_internal.py:137`，再走 `model_gateway.stream_chat`）；**工具调用**经 `platform.ts::executePlatformTool` 回调 `/internal/dsh/tools/execute`（`dsh_internal.py:266`）→ `nodes.py:1955::_execute_tool_call`
7. 工具实现都在 `nodes.py`：内置文件工具 `workspace_list_files / read_file / write_file / delete_file`、办公工具 `spreadsheet_tool / document_tool / presentation_tool / pdf_tool / text_tool / image_tool / archive_tool / web_tool / image_generation_tool`（:176-324，实际执行转发到 skill_runner 的 builtin_tools）；技能 `load_skill / read_skill_resource / run_skill_script`（:1623-1640，走 `skill_runner_client`）；连接器端点按 `_build_tools`（:1444）每个 bound endpoint 各发一个 function-tool；`rag_search`（:2414）；企业模块动作经 `subsystem_action_service`
8. 每个文件工具先过 `nodes.py:407::_resolve_tool_workspace` + `workspace_permission_service.resolve_workspace_intent`（:186）——用关键词判断这轮是否"权限提问"/"点名了哪个空间"
9. 回到 `runner.py::_consume_dsh` 收尾：技能文件交付检查 `_requires_skill_file_delivery`（:96，不满足自动续跑一次并 `text_retract`）、`message_verification.contains_unverified_tool_success_claim`、拼最终文本
10. `_finish`（:330）：`save_memory → extract_memory → judge → write_run_log`（`nodes.py:2459-2700`），落 `agent_runs` / `agent_run_events` / `task_messages`；`persist_run_events` 让 GET `/stream` 能回放

进程重启时 `main.py:38-47` 把所有 queued/running run 标 error。

### 3.3 (c) 文件上传与预览

**上传**（前端一律直传，`client.ts` 阈值 0 字节，见 hist2）：
1. POST `/terminal/workspaces/{ws}/uploads/initiate`（`terminal.py:918`）→ `workspace_governance_service.initiate_direct_upload`（:77）→ `storage_gateway_service.sign_browser_upload`（:172）拿签名/分片会话，写 `workspace_upload_sessions`
2. 浏览器直传 OSS（分片经 `/uploads/{id}/parts/{n}/sign`）
3. POST `/terminal/uploads/{id}/complete` → `complete_direct_upload`（:171）：`inspect_object` 核对大小 → `workspace_service.upsert_file`（:128，传 `content_ref=oss://…`）→ `parse_status="queued"` → `sync_current_version` → 按后缀预热预览 job → 审计 `upload_completed`
4. 旧路径 `/files/upload` 走 `workspace_service.ingest_uploaded_file`（`terminal.py:882`），仅 ≤1MB 代理上传

**解析**：`app/workers/workspace_parser.py` 每 2s `claim_one`（`FOR UPDATE SKIP LOCKED`，租约 6 分钟）→ 从 OSS 下载 → `doc_parser.extract_text` → 写 `extracted_text`（>100MB 直接标 unsupported）。这是智能体 `workspace_read_file` 读到的内容。

**预览**：POST `/files/{id}/preview-session`（`workspaces.py:459` / terminal 同名）→ `workspace_preview_session_service.create_preview_session`（:113）按后缀+大小决定 mode：
- pdf → `pdfjs`（>20MB `strict_range`）；也可走服务端逐页栅格 `/pdf-preview/pages/{n}`（`workspace_pdf_preview_service`）
- docx/xlsx ≤ `LOCAL_OFFICE_MAX_BYTES` → `browser_office`（浏览器解析）
- 大 csv / 任何 xlsx 超限 → 入队 `spreadsheet_rows` job
- pptx → WebOffice token（`storage_gateway_service.generate_weboffice_token`，需 `workspace_weboffice_enabled`）失败则 `fallback`
- legacy doc / 大 word → `enqueue_fallback` → `app/workers/workspace_preview.py`（LibreOffice 转 PDF，advisory lock 全局单并发，3 次重试指数退避）写回 `workspace_preview_jobs.output_ref`

### 3.4 (d) 权限解析——两套解析器

终端用户主体 `app/auth/user_auth.py:27::CurrentUser` 由 `current_user_for_user`（:77）构造，字段来自 `role_service.rbac_for_user`（:180）：`role_ids`、`permission_codes`、`effective_data_scopes{unrestricted, department_ids, own_only}`（按 role.data_scope = all / department / department_and_children / custom_departments / self 计算）。

**解析器 A —— 资源可见性**（技能、本体、RAG、智能体、数据接口）：`app/services/scope_service.py::effective_scope_set`（:55）/ `scope_filter`（:69）。部门集合 = 主部门 + `effective_data_scopes.department_ids`（即角色 data_scope），`unrestricted` 则整个 department 类型都可见。

**解析器 B —— 工作空间能力**：`app/services/workspace_permission_service.py::capabilities`（:65）。部门集合来自**权限码** `workspace.department.read:<id>` / `workspace.department.upload:<id>`（`_department_workspace_access` :37），`*` 通配。矩阵：`read = own | 主部门或授权部门 | 同团队 | 组织空间`；`create/update = own | 部门 upload 码`；`delete = own`；`publish` 硬编码 False（:110）。

后果：同一个用户可能"看得到 B 部门的技能，看不到 B 部门的文件"（hist2 区域 2）。改任何一处部门授权逻辑要同时看两个文件。

管理端另有 `admin_auth.py::assert_org_access`（org 级管理员只能碰自己组织）；代理侧是 §3.1 的 `permission_resolver`——共三套。

## 4. 数据模型主干

按外键计数（`grep ForeignKey app/models`）：`organizations.id` 被 47 处引用，是多租户根；其次 `users.id` 19、`admins.id` 13、`enterprise_applications.id` 12、`departments.id` 9、`workspace_files.id` 8。

```
organizations ─┬─ departments (parent_id 自引用树) ─ teams
               ├─ users ─ user_roles ─ roles ─ role_permissions / role_data_departments
               ├─ admins（超管 org_id=NULL；组织管理员绑定 org）
               ├─ api_keys（org/dept/team 三级，lr_sk_*）── audit_logs / budget_usage
               ├─ llm_providers ─ model_deployments ；routing_policies ；dlp_rules
               ├─ workspaces(scope_type: organization/department/team/user, scope_id)
               │    └─ workspace_files ─ workspace_file_versions ─ workspace_preview_jobs
               │         workspace_folders / workspace_upload_sessions / workspace_audit_events / workspace_share_links
               ├─ agents ；tasks ─ task_messages ；agent_runs ─ agent_run_events ；agent_messages ；memories
               ├─ rag_collections ─ rag_folders / rag_documents ─ rag_chunks(pgvector)
               ├─ skill_folders ─ skill_files / skill_versions / skill_executions ；scope_manager_assignments
               ├─ ontology_folders ─ ontology_files ；tool_connectors ─ tool_endpoints ；data_systems ─ data_interfaces
               ├─ enterprise_applications ─ grants / tool_bindings / integrations / actions / action_requests
               │         / events / event_routes / event_deliveries ；cross_department_work_items
               ├─ multimodal_jobs ；voice_profiles ─ voice_profile_grants / voice_authorization_records
               ├─ module_deployment_profiles ─ module_deployments ；ecs_runtimes ─ ecs_module_releases
               └─ organization_slug_aliases
platform_extension_sources / catalog_entries / releases / release_events（平台级，无 org）
```

关键约束：
- `workspace_files` 唯一键 `(workspace_id, path)` **不含 deleted_at**——软删记录仍占路径，`upsert_file` 因此必须"复活并覆盖"（`workspace_service.py:157-198` 注释）
- `workspace_files.content_ref`：文本文件等于 path，二进制等于 `oss://` 引用（`storage_gateway_service.is_object_ref`）；`workspace_file_versions` 复制同一字段
- 技能/本体/RAG/工作空间都有 `scope_type + scope_id`，由 §3.4 解析器 A 过滤
- 长期记忆 `memories.scope_type NOT NULL`（`models/memory.py:30`）
- 节点↔空间/记忆一一配对由 `workspace_lifecycle` / `memory_lifecycle` 保证（建部门自动建同名空间）

## 5. 后台 worker 与轮询循环

| 进程/任务 | 文件 | 触发与间隔 | 说明 |
|---|---|---|---|
| workspace-parser | `app/workers/workspace_parser.py::main` | 每 2s 抢 `parse_status=queued` 或租约过期 6 分钟的 processing 行 | 单并发，解析超时 5 分钟；>100MB 跳过 |
| workspace-preview | `app/workers/workspace_preview.py::main` | `workspace_preview_job_poll_seconds`=1s；pg advisory lock 全局单并发 | LibreOffice 转 PDF / 表格分页 JSON；3 次重试 30s·2^n |
| storage-lifecycle | `app/workers/storage_lifecycle.py::main` | `storage_lifecycle_interval_seconds`=3600（下限 60） | `run_cleanup`（回收站到期物理删、上传会话过期、inline 技能包迁移）+ 每天一次 `reconcile_orphan_objects`，同一 session，任一异常整体回滚 |
| multimodal-worker | `app/workers/multimodal_worker.py::run_forever` | 1s 轮询 `multimodal_jobs`，租约 600s | ffmpeg 归一化 → `model_gateway.transcribe_audio / synthesize_audio` |
| 子系统同步 | `subsystem_integration_service.py:954::run_subsystem_sync_scheduler` | backend lifespan 内 asyncio task，`subsystem_sync_poll_seconds`=30（下限 15） | 对每个 `sync_enabled` 的企业模块拉 manifest + 事件（sequence 必须严格递增，否则整轮失败） |
| 扩展目录同步 | `platform_extension_discovery.py:343::run_catalog_sync_scheduler` | 每小时检查，24h 一次真同步 | 拉 `extension_catalog_community_url` |
| 扩展 release 恢复 | `platform_extension_service.sync_active_release_to_runtime` | 启动一次 | DSH 重启后把 DB 里 active manifest 推回 runtime |
| Skill 安装续跑 | `skill_runner_client.resume_pending_installs` | 启动一次（`code_skills_enabled`） | 重启前中断的依赖安装 |

后三项在 `app/main.py:57-73` 注册；worker 前四项是 compose 独立容器（§6）。

## 6. 部署拓扑

### 6.1 compose 服务表（`docker-compose.coolify.yml`）

| 服务 | 镜像（registry `127.0.0.1:5000/zhuojian/…`） | 角色 | 端口 | 健康检查 | 内存 | depends_on |
|---|---|---|---|---|---|---|
| postgres | `ai-platform-pgvector-pg16@sha256` | DB，只监听 127.0.0.1 + data_plane 10.0.10.10 | 5432(内) | `pg_isready` 5s×12 | 2G | — |
| redis | `ai-platform-redis7@sha256` | 准入队列/租约/缓存，AOF | 6379(内) | `redis-cli ping` | 512M | — |
| mock | `ai-platform-mock-app@sha256` | 14 个 mock 业务系统 | 8010 | GET /health | 256M | — |
| skill-runner | `ai-platform-skill-runner-app@sha256` | 执行 Skill 脚本；read_only + cap_drop ALL + tmpfs 1G；**无 `init:`** | 8020 | GET /health | 3G, pids 512 | — |
| dsh-runtime | `ai-platform-dsh-runtime-app@sha256` | DSH agent loop，`DSH_RUNTIME_HARD_CONCURRENCY`=14 | 8030 | node fetch /health | 1536M | — |
| extension-builder | `ai-platform-extension-builder-app@sha256` | 构建扩展；read_only + tmpfs 512M | 8040 | node fetch /health | 1G, pids 256 | — |
| backend | `ai-platform-backend-app@sha256` | FastAPI；启动命令 `alembic upgrade head && uvicorn` | 8000 | GET /health, start 30s | 2560M | postgres, redis, mock, skill-runner, dsh-runtime, extension-builder 全部 healthy |
| workspace-parser | 同 backend 镜像 | `python -m app.workers.workspace_parser` | — | grep /proc/1/cmdline | 1536M | backend |
| workspace-preview | `ai-platform-workspace-preview-app@sha256`（`Dockerfile.preview`，含 LibreOffice） | `app.workers.workspace_preview` | — | 同上 | 2G, pids 256 | backend |
| storage-lifecycle | 同 backend 镜像 | `app.workers.storage_lifecycle` | — | 扫 /proc 找进程 | 384M, pids 128 | backend, skill-runner |
| multimodal-worker | 同 backend 镜像 | `app.workers.multimodal_worker` | — | grep /proc/1/cmdline | 1536M, pids 256 | backend |
| frontend | `ai-platform-frontend-app@sha256` | nginx：静态 + `/api /v1 /mcp` 反代到 backend:8000（`frontend/nginx.coolify.conf:56`），`client_max_body_size 50m`（:42） | 80（Coolify 公网入口） | wget /health | 256M | backend |

网络：`data_plane`（internal, 10.0.10.0/24）只有 postgres/redis/backend/四个 worker；skill-runner、dsh-runtime、extension-builder、mock 看不到 DB。

### 6.2 镜像 pin 流程

- 代码提交后，作者在本地/构建机构建镜像推到 Coolify 宿主机私有 registry `127.0.0.1:5000`，再提交一个 `chore(deploy): pin …` commit 只改 `docker-compose.coolify.yml` 的 `@sha256`（例：`3435cb8` 只改 frontend 一行）。Coolify 监听 `main` webhook 自动 `compose up`。
- 所以 **`main` 上的源码 ≠ 线上跑的代码**，线上 = compose 里 12 个 digest；git log 里 `chore(deploy): pin` 通常落在代码 commit 后 5–15 分钟。
- 镜像分两层：`infra/base-images/*.Dockerfile` 装依赖（backend-deps 在 `/app` 做 `pip install -e .`），`llm_router/backend/Dockerfile.coolify` 从 deps base `rm -rf /app` 后 `COPY . .`（ca5d4f8 加的，否则旧文件残留）。`Dockerfile.preview` 不装依赖，靠 office base 与 backend pyproject 同步。
- 构建脚本不在仓库内（`scripts/` 只有备份/清缓存），无法从代码验证推送方式。

### 6.3 staging vs prod

- **staging**：`ai-platform.staging.zhuojianai.com`，`COOLIFY_DEPLOYMENT.md` 描述的就是它；compose 所有默认值（`STORAGE_GATEWAY_URL`、`MODULE_SAAS_ORIGIN`、`TRAEFIK_DOCKER_NETWORK`、各 `*_ORG_ALLOWLIST=aifabei`）都是 staging 的。
- **prod（academy）**：同一个 compose，另一个 Coolify app，截至审计停在 `4bd27bf`（2026-08-29，落后 161 commit、13 个迁移），且未覆盖的默认值会指向 staging 存储网关（hist1 C4）。
- 旧式部署 `docker-compose.yml + docker-compose.prod.yml`（`build:` 而非镜像，域名 infra.aievolve.org.cn）仍在仓库，与 Coolify 栈不是一回事。

### 6.4 环境变量真相源

- 后端读 `app/config.py::Settings`（pydantic-settings，`.env` 在 `llm_router/backend/`）。**默认值是本地开发值**（DB 5434、Redis 6381、所有 sidecar `localhost`）。
- Coolify 部署时真相 = Coolify Application 的环境变量 + compose 默认值。config 有、compose 没写的字段线上只能用代码默认（如 `subsystem_sync_poll_seconds`、`storage_orphan_grace_days`、`dlp_stream_*`）。
- 两处默认值不一致的例子：`workspace_weboffice_enabled` config 默认 False，compose 默认 true；`original_preview_enabled` 同样。本地跑的是 fallback 路径，线上是 WebOffice 路径。
- 前端：`VITE_API_BASE_URL`（`client.ts:5`），线上为空走同源 nginx。

## 7. 测试与验证现状

- 后端：`make test` → `cd llm_router/backend && pytest tests/ -v`（`Makefile:25`）。`tests/conftest.py` 的 `db_engine` fixture `autouse`，每个测试都 `create_all` + `CREATE EXTENSION vector`，默认连 `localhost:5434/ai_infra_test`（`conftest.py:27-30`）。**没有 Postgres+pgvector 一个测试都跑不了**，没有纯单元 lane。43 个测试文件；`terminal.py` 81 个端点只有 1 个 URL 被测过，`workspaces.py` 0 个（hist0 §2）。
- 前端：无 vitest/jest。`package.json` 只有 3 个 node 脚本（`test:presentation` 11 断言、`test:subsystem-bridge` 10 断言、`test:e2e:attachments` 需 Playwright + 真实环境）。
- dsh_runtime：`node --test dist/tests/*.test.js`（需先 build）。skill_runner：`test_app.py` 独立 pytest。
- **无 CI**：仓库没有 `.github/`、gitlab-ci、pre-commit。没有迁移冒烟测试（`alembic upgrade head` 对空库）。
- 验证线上只能：Coolify 健康 + `/health` + 手点。

## 8. 已知薄弱区与历史教训（来自 2026-09-03 审计的三份考古）

审计报告与原始数据见 `docs/audit/`。以下是结构性的，不是单条 bug：

**8.1 半途而废的迁移是"小 bug"主因**
- 永久分享链 → 限时分享（`e1be902`）：后端 `terminal.py:1420` 旧路由改成无条件 410，前端 `BrowserDrawer.tsx` 仍拼旧 URL。
- LangGraph 协调器 → DSH runtime（`8be6543`）：删了 `test_agent_retracts_unverified_tool_success_and_retries`，重试计数断言未恢复；`dsh_internal.py` 曾把 4000 字 preview 当 tool result 返回（H2）。
- 浏览器预览 → 服务端栅格 → preview-session + worker（`a245106 … 16eb286 … 0f8103c`）：15 天换 3 套架构，PDF 一天内切 4 次渲染器；遗留 `workspace_preview_session_service.py:298` 的 `failed and attempt_count<3` 永假、docx≤20MB 从不入队"缓存"。
- 单部门 → 多部门（`de46190`）→ 单部门+RBAC（`214a895`, `912f392`）→ 权限码（`f26906f`）→ 角色能力（`81637d9`）：三天内反复，留下 §3.4 两套解析器；测试断言两次被改成迎合代码（`c50aedc`、`81637d9` 同一行一天翻两次）。

**8.2 启发式叠启发式**
- 智能体"只 load_skill 不干活"的每次修复都在 Python 桥接层加关键词判断（`runner.py::_requires_skill_file_delivery`、`message_verification.py`、`dsh_internal.py::_identical_failure_blocked`、`workspace_permission_service.resolve_workspace_intent`），从未改 DSH 端循环终止条件。副作用：分析类请求被撤回文本（hist2 区域 3.1）、含"是否"的普通指令曾被当权限提问拒绝所有文件工具（3435cb8 时 `:211`；本分支已改）。

**8.3 软删除占唯一键**
- 用户名、角色、授权、slug、workspace path 都因 tombstone 占键出过 409，每次补一个"释放"补丁（`1628588`、`14753fa`、`e96c76a`）。`organization_slug_aliases.slug` unique 无 deleted 过滤，删组织不清别名。

**8.4 部署面**
- 4 次失败部署（`972175e`、`38e3845`、`7982e5d`、`404dc5f`）全是迁移或镜像缺陷：revision id 超过 `alembic_version` VARCHAR(32)（`f26d810`）、SQL 别名用保留字 `grant`（`3453520`）、deps base 残留旧 `/app`（`ca5d4f8`）。backend 启动串 `alembic upgrade head &&`，失败即 frontend 起不来 = 全站 502。
- nginx 50MB 上限 < 技能包/RAG 文档 100MB 代码上限（`nginx.coolify.conf:42` vs `skill_import_service.py:283`），413 无中文提示。
- `storage_lifecycle` 一小时的清理与 orphan 扫描同 session，网关 503 即整体回滚，但 OSS `delete_object` 已执行不可回滚。
- skill-runner 是唯一没 `init: true` 的服务，却 fork 用户进程（僵尸累积到 pids 512）。
- `0049` 删多余部门成员、`0054` 软删组织级带 scope_id 的授权——prod 从 4bd27bf 升级前必须 pg_dump。

**8.5 测试证据被削弱的模式**（hist0 §4）：修 bug 的 commit 顺手把断言改成新行为而无理由说明（`dce1570` 删 publish 测试并把 `publish` 硬编码 False；`5ce44c9` 把"导入新版自动激活"改成不激活；`16eb286/f26906f/bcfdb6e` 三天改三次分片大小断言）。看到"fix + 测试断言翻转"要追问。

## 9. 改代码前必读清单

1. **线上跑的是 compose 里的 digest，不是 main HEAD。** 改完代码没 `chore(deploy): pin` 等于没上线；pin 前先对空库跑 `alembic upgrade head` 并 `python -c "import app.main"`。
2. **compose 默认值全是 staging。** 给 prod 加变量要同时列进 Coolify prod app；`config.py` 默认值又是本地值，三处对不齐时以 Coolify 面板为准。
3. **权限判定有三套**：代理侧 `permission_resolver`、资源可见性 `scope_service`（role.data_scope）、工作空间 `workspace_permission_service`（permission_codes）。改部门授权要同时看后两者，并核对 `role_service.rbac_for_user`。
4. **改 `workspace_service.upsert_file` / `content_ref` 要看全部消费方**：`workspace_parser.py`（下载解析）、`workspace_preview.py` + `workspace_preview_session_service.py`（预览来源）、`workspace_governance_service.py`（版本/分享/物理删除）、`storage_lifecycle_service.py`（orphan 对账）、`nodes.py` 文件工具、`workspace_pdf_preview_service.py`。软删记录仍占 `(workspace_id, path)`。
5. **智能体工具结果必须完整返回给模型**：`dsh_internal.py::execute_tool` 返回 `message["content"]`，`preview` 只给事件/trace（4000 字截断）。改 `nodes._execute_tool_call` 返回值形状要同步这里和 `test_dsh_bridge.py`。
6. **终端 SSE 是"后台任务 + 回放"**：`run_registry` handle 在进程内存，多副本 backend 会丢 live 回放；GET `/stream` 兜底靠 `agent_run_events` 落库。改事件格式要同时改 `persist_run_events` 和 `Terminal.tsx` 的单事件派发。
7. **DSH runtime 调 backend 靠 15 分钟 `run_token`**（`dsh/registry.py`），token 与 `DshRunContext` 只在发起 run 的那个 backend 进程里；超时或多副本都会 401 "expired run token"。
8. **技能新版本导入后不自动激活**（`skill_import_service`，`113d912` 后），必须调 `/terminal/skill-versions/{id}/activate`。
9. **每个 pytest 都要 Postgres 5434 + pgvector**；新加纯函数测试也逃不掉。前端零测试，改 `client.ts` 阈值/`OriginalFilePreview` 分发逻辑只能手测。
10. **修 bug 别改断言方向**：断言被翻转时在 commit message 写清楚为什么行为反了；`publish`、多部门、分片大小已经各翻过一次。

## 附：本文未能从代码验证的点

- 镜像构建/推送到 `127.0.0.1:5000` 的脚本不在仓库，pin 流程按 git 历史推断。
- prod（academy）当前 SHA `4bd27bf` 与其 Coolify 环境变量来自 hist1 考古，未直接访问服务器。
- `dsh_runtime/vendor` 里 `@deepseek-ai/dsh-*` 的内部行为（agent loop 终止条件）未读源码（写作时为 rc.5，B2 后为 rc.8）。
- 本文写作时 `fix/audit-2026-09-03-high` 分支有 16 个文件在并行修改（含 `dsh_internal.py`、`workspace_permission_service.py`、`runner.py`），§8 引用的行号以 `main@3435cb8` 为准。

## DSH（DeepSeek Harness）接入现状与路线图（2026-09-05）

> 基线：分支 `feat/dsh-native-policies`。`dsh_internal.py` / `runner.py` / `dsh_runtime/src` 正在并行修改，本节优先给 `::函数` 引用，行号只在函数名不够时给。上游事实来自本地克隆 `D:\claude project\deepseek harness\deepseek-harness`（HEAD `141eb6f`，release/dsh-0.1.0-rc.8，浅克隆）。

### 现状

**版本与包**
- 平台 vendored `@deepseek-ai/dsh-*` **0.1.0-rc.8**（B2 已完成，分支 `feat/dsh-rc8-upgrade`）：`dsh_runtime/package.json` 23 个 tgz（cordis 4.0.1、schemastery 3.18.1 与 rc.5 时字节相同；17 个原有 dsh 包升到 rc.8；新增 4 个 provider：`dsh-session-persistence-jsonl`、`dsh-code-runtime-worker-thread`、`dsh-repeat-tool-reminder`、`dsh-tool-call-timeout-policy`），清单与打包步骤见 `dsh_runtime/VENDOR.md` + `dsh_runtime/vendor/SHA256SUMS`。上游克隆 HEAD `141eb6f` 即 rc.8，与 vendored 同版。
- rc.5→rc.8 对 `dsh_runtime/src` 用到的 API 零破坏：agent-loop / tools / timeout / user-approval / session-persistence / agent / system-prompt 的 `.d.ts` 逐字相同；只有 llm（`ReplayEnvelope`、`offloadRequestImages`、重试默认 2→5）、session（`assistant/message` 新增 `interrupted?: true`）、attachment（图片准入）是纯新增。行为变化一处：agent-loop 在中途 abort 时会把已流出的文本前缀作为 `interrupted: true` 的 `assistant/message` 落盘（runtime.ts 的 cancel 路径不消费 finalText，不受影响）。
- DSH 版本号硬编码点：`dsh_runtime/src/extensions.ts::DSH_VERSION`（唯一常量，`runtime.ts::health` 与 `verifyRelease` 都引用它）、`extension_builder/src/builder.ts::compatibleDsh`（:250/:321/:379 三处字面量）、`platform_extension_catalog.py`（`CORE_PLUGINS[*].version` + `baseline_manifest().dsh_version`）、`platform_extensions.py` 两处文案、`platform_extension_discovery.py` / `platform_extension_service.py` 的 `runtime_requirements`、`extension-sdk/templates/*/ai-platform.extension.json`。升级时 `grep -rn "rc\.8" --exclude-dir=node_modules --exclude-dir=vendor` 全改。
- 部署前置：`infra/base-images/dsh-runtime-deps.Dockerfile` 产出的 `AI_PLATFORM_DSH_RUNTIME_DEPS_BASE` 内嵌旧 lockfile 的 node_modules，**必须先重建该基础镜像**（它现在还要 COPY `dsh_runtime/pnpm-workspace.yaml`：pnpm 11 把 koffi 的 install 脚本记为 `allowBuilds: koffi: false`，否则 `ERR_PNPM_IGNORED_BUILDS` 直接失败）。重建脚本 `scripts/build-dsh-runtime-deps.sh`，发版顺序见 `COOLIFY_DEPLOYMENT.md`「升级 DSH 版本后的发版步骤」。已存在的 `platform_extension_releases` 行 manifest 里仍是 `dsh_version: 0.1.0-rc.5`，rc.8 运行时会在 `verifyRelease` 拒绝重新激活；现在由后端自愈：`platform_extension_service.py::heal_active_release_version`（启动时 `sync_active_release_to_runtime` 与每次 `ensure_baseline` 都会调）把平台基线按目录重生成、把兼容的自定义发布只改版本号（新行取代旧行，旧行 `superseded`，记 `release_version_healed` 事件），不兼容的自定义发布只告警不改；alembic `0069_dsh_release_rc8` 另把只含平台项的历史行改到 rc.8。版本常量 Python 侧统一为 `platform_extension_catalog.py::DSH_VERSION`。

**运行拓扑**
- `runtime.ts:99-104` 只加载 6 个 cordis 插件：LlmRuntime / SessionStore / SystemPrompt / ToolRuntime / AgentRegistry / AgentLoop（`maxParallelToolCalls: 1`）。dsh-timeout 等其余 vendored 包一个都没 import。
- 模型桥：`dsh_runtime/src/platform.ts::PlatformLlmAdapter.stream` → POST `/api/v1/internal/dsh/model/stream`（`app/api/dsh_internal.py::model_stream`）→ `model_gateway.stream_chat`。DSH 内部没有任何 provider，模型永远经平台网关。
- 工具桥：`agentCtx.tools.register` 逐个注册 `RunRequest.tools`（`contracts.ts::ToolSpec`，现只有 name / description / input_schema）→ `platform.ts::executePlatformTool` → POST `/internal/dsh/tools/execute`（`dsh_internal.py::execute_tool`）→ `app/agents/graph/nodes.py::_execute_tool_call`。
- 会话：每 run 一个 session `platform-${run_id}`，不跨轮复用；历史消息（`RunRequest.messages`）每轮由 Python 重渲染进 system prompt；系统提示词由 `nodes.py::prepare_dsh_turn` 拼好后作为单一 section 注入 SystemPrompt 插件。DSH 自己的持久化 / compaction / settings 都没启用。
- 入口：`runner.py::_consume_dsh` POST `dsh_runtime/src/server.ts` 的 `/v1/runs`（:50），并发闸 `DSH_RUNTIME_HARD_CONCURRENCY`=14（`server.ts:14`）。

**谁走 DSH、谁不走**
- 走：终端对话、智能体测试广场、企业应用助手——三者都收口到 `runner.py::stream_general_agent`。
- 不走：`nodes.py::judge`、`nodes.py::extract_memory`（两者直接 `llm_client.chat`）、多模态 worker、skill_runner 沙箱、MCP 工具层（`app/mcp/server.py` 12 个 `@mcp.tool()`，DSH 看不到；§2 写的「9 个平台能力」已过期）。

**vendored 但未接线**
- dsh-code-runtime、dsh-session-persistence、dsh-user-approval（`platform_extension_catalog.py:74-81` 标「平台审批事件与应答通道尚未适配，禁止发布」）、dsh-attachment、dsh-settings、dsh-scope、dsh-timeout（catalog `:65-71` 声明 `enabled: True`，但 runtime.ts 从未 import）、dsh-typert-protocol / dsh-typert-registry、dsh-invariants。
- B2 之后 vendor 里多了 4 个 provider（jsonl 持久化、worker-thread 代码运行时、repeat-tool-reminder、tool-call-timeout-policy），**都只是 vendored，`runtime.ts::buildContext` 一个都没 `ctx.plugin(...)`**；C1 / C2 接线时直接 import 即可。subagent（`packages/subagent/`）、mcp-client（`packages/mcp/mcp-client`）仍只在上游。注意 jsonl 拉进了原生依赖 `koffi`（仅 Windows 路径 import，Linux 容器不加载），见 `dsh_runtime/pnpm-workspace.yaml`。

### Phase A（本分支实施）：把循环策略搬进 DSH 事件管道

动机：§8.2 的循环控制全在 Python 桥接层堆关键词。Phase A 把「重复失败怎么拦 / 没产出怎么续 / 取消怎么算」搬到 DSH 事件钩子里，Python 只下发策略参数。

| 改了什么 | 替掉了什么 | 怎么验 |
|---|---|---|
| 新 `dsh_runtime/src/policies.ts`：`tools/post-execute` 钩子按 (name, arguments) 指纹记连续相同失败并 block；跟踪文件产出工具成功次数 | `dsh_internal.py::_identical_failure_blocked / _record_tool_outcome`（原 `:54-80` 指纹计数器，已删） | 同一失败工具连调 → 第 N 次 `tool_result.ok=false` 且事件流出 `policy{kind: repeat_failure_block}`；`node --test dist/tests/*.test.js` |
| `agent/turn-stopping` 钩子 + `agent.steer()`：`require_file_output` 且未产出文件时，在**同一 session 同一轮**注入 nudge 续跑，最多 `max_nudges` 次 | `runner.py:266-283` 的 `run_id+"-continuation"` 二次 run（Stop 无法取消，且要把已流出文本整段 `text_retract` 重跑） | 选技能只 load_skill 不写文件 → SSE 出 `policy{kind: continuation}`，无 `text_retract`；nudge 期间 Stop 立即生效 |
| `turn/end` 收到 aborted → 事件 `status: cancelled` | Python 侧靠异常推断取消 | Stop 后 `agent_runs.status=cancelled` 而非 error |
| `ToolSpec` 新字段 `timeout_ms / concurrency_safe / max_model_chars / kind`；`registerTool` 透传 `timeoutMs / isConcurrencySafe / finalizeContent` | 截断只在 Python `preview`（§9.5）、无超时、全串行 | 超时工具返回 ok=false + `policy{kind: tool_timeout}`；`max_model_chars` 截断在 DSH 侧生效 |
| 工具执行硬超时接入 dsh-timeout；`maxParallelToolCalls` 由 `DSH_MAX_PARALLEL_TOOL_CALLS` 控制（默认 4） | `runtime.ts:104` 硬编码 `maxParallelToolCalls: 1` | 一轮多个 `concurrency_safe` 读工具并发执行；写工具仍串行 |
| `RunRequest` 新字段 `completion_policy {require_file_output, file_output_tools, max_nudges, nudge_text}`；`RuntimeEvent` 新增 `policy`（continuation / repeat_failure_block / tool_timeout） | Python 侧关键词启发式决定是否续跑 | `persist_run_events` 落库可见 `policy` 事件；`Terminal.tsx` 单事件派发对未知类型不报错 |
| `runner.py::_requires_skill_file_delivery` 只算策略：仅用户明确要文件时 `require_file_output=true` | hist2 区域 3.1：分析类请求被撤回文本 | 分析类提问 + 技能 → 正常出文本，无 `text_retract` |
| `read_memory / write_memory` 作为 `kind=memory` 平台工具喂给 DSH；本轮已 write_memory 则 `_finish` 跳过 `extract_memory` | 每轮无条件跑一次 `nodes.py::extract_memory`（一次 LLM 调用） | 模型本轮调了 write_memory → run 事件无 extract_memory step，`memories` 表有新行 |

新契约速查（字段名以 `dsh_runtime/src/contracts.ts` 为准，此处只列增量）：

```
ToolSpec      += timeout_ms?: number          // 硬超时，走 dsh-timeout
                 concurrency_safe?: boolean   // true 才允许与其他工具并发
                 max_model_chars?: number     // 喂给模型的 content 上限，DSH 侧截断
                 kind?: 'file_output' | 'memory' | ...   // policies.ts 按 kind 识别产出/记忆工具
RunRequest    += completion_policy?: { require_file_output, file_output_tools, max_nudges, nudge_text }
RuntimeEvent  += { type: 'policy'; kind: 'continuation' | 'repeat_failure_block' | 'tool_timeout'; ... }
env           += DSH_MAX_PARALLEL_TOOL_CALLS（默认 4）
```

契约同步点（改任一处要同时看）：`contracts.ts` ↔ `runner.py` 组装 `RunRequest` 处（`:208` 附近）↔ `dsh_internal.py::execute_tool` 返回形状 ↔ `persist_run_events` ↔ `Terminal.tsx` 事件派发 ↔ `tests/test_dsh_bridge.py`（指纹计数器断言要删）。

Phase A 验证清单：
1. `cd dsh_runtime && npm run build && node --test dist/tests/*.test.js`——policies 单测跟 `runtime.test.ts` / `extensions.test.ts` 同目录。
2. `cd llm_router/backend && pytest tests/test_dsh_bridge.py -v`（需 Postgres 5434 + pgvector，§7）。
3. 终端手测三例：① 技能 + 明确要文件 → 出 `policy{continuation}`，最终有 `tool_result` 产出文件；② 技能 + 分析类提问 → 只出文本，无 `text_retract`；③ 续跑途中点 Stop → `status: cancelled`，`agent_runs.status=cancelled`。
4. 事件落库：`agent_run_events` 里能查到 `policy` 事件；GET `/tasks/{id}/stream` 回放不丢。
5. 回归：`test_dsh_bridge.py` 不再引用 `_identical_failure_blocked`；`grep -rn "\-continuation" app/agents/dsh/runner.py` 为空。

### Phase B / C（路线图，未实施）

| 项 | 内容 | 前置 | 替换掉什么 | 风险 |
|---|---|---|---|---|
| B1 接 dsh-user-approval | 后端 `/internal/dsh/approval/request` 挂起 Future；SSE 新事件 `approval_request`；POST `/terminal/tasks/{id}/approvals/{approval_id}` 应答；Future 120s 超时视为拒绝 | 前端审批卡（`terminal.py` 现 0 处 approval） | `workspace_permission_service.resolve_workspace_intent` 的权限提问启发式（§3.2 第 8 步） | Future 在发起 run 的 backend 进程内存里，多副本必丢（同 §9.6/9.7）；120s 内不答 = 工具失败 |
| ~~B2 rc.5→rc.8 升级~~（已完成，`feat/dsh-rc8-upgrade`） | 用上游 `pnpm pack`（`scripts/release/pack.ts` 同一命令）逐包打 tgz 进 `dsh_runtime/vendor/`；版本常量收口到 `extensions.ts::DSH_VERSION`；步骤见 `VENDOR.md` | 上游 `docs/rescope.md` 已核：cordis / schemastery 在 rc.8 仍是 4.0.1 / 3.18.1 且字节相同，无需换包 | — | 钩子签名零变化（见「现状」）；已发布 release 行的 `manifest.dsh_version` 仍失配，需重新发布基线；deps 基础镜像必须重建 |
| C1 dsh-session-persistence（jsonl） | sessionId=`platform-task-${task_id}`，`ctx.agents.resume` + followup 续会话；PostgreSQL 仍是事实源 | B2（jsonl provider 只在 rc.8）；dsh-runtime 容器挂持久卷 | 每轮把 `RunRequest.messages` 重渲染进 system prompt | jsonl 丢/坏要从 `task_messages` 重建的 digest 回退；`/sessions` 卷无人清理；多副本 dsh-runtime 会话不共享 |
| C2 Code Mode | `WorkerThreadCodeRuntime` + tools mode `both`；**不替换** skill_runner | B2；重算堆上限 | 无（新增能力） | 1536M 容器（§6.1）× 14 并发 worker，各自独立 heap，`--max-old-space-size` 要重算；worker 内可直接打 backend 网络 |

已否决（一句话理由）：
- typert（protocol / registry）：工具 schema 由 Python 生成，DSH 侧再套一层类型无消费者。
- invariants：断言库，无业务面。
- scope / settings：租户配置在 PostgreSQL 与 Coolify 环境变量（§6.4），不再加第三处配置源。
- subagent 改造 judge / extract_memory：两者各是一次 `llm_client.chat`，套 agent loop 只加延迟。
- attachment：附件已在 Python 侧解析成文本进 prompt（§3.3 解析链）。
- compaction：会话每 run 一个，没有长会话可压；C1 落地后再议。
- llm-retry：模型调用经 `model_gateway`，重试归平台侧，DSH 内再套一层会双重重试。
- sandbox-local：沙箱是 skill_runner（read_only + cap_drop ALL，§6.1），不引第二套。

### 对外兼容 DSH（客户本地 dsh CLI 接平台，未实施）

**已核实阻塞**
- 上游 mcp-client 只支持静态 headers 鉴权：`packages/mcp/mcp-client/src/transport.ts:45-48` 把 `config.headers` 原样放进 `requestInit`，无 OAuth 流程。
- 平台 MCP 只挂 OAuth-only：`app/main.py:170` 挂 `/mcp/organizations`（`mcp/server.py::organization_mcp_app`）；API-key 版 `mcp/server.py::mcp_app()` 未挂载，`main.py:168-169` 注明刻意为之——员工角色变更必须即时吊销个人 AI 访问。
- 两条叠加：dsh CLI 现在接不上平台 MCP，不是配置问题。

**今天就能用的**
- 上游 `llm-deepseek` 的 `baseURL`（`packages/llm/llm-deepseek/src/index.ts:70`，请求打 `${baseURL}/chat/completions`，`adapter.ts:341`）指向平台 `/v1`。平台端点：POST `/v1/chat/completions`、POST `/v1/messages`、GET `/v1/models`（`app/proxy/router.py:42,61,80`）；key 形如 `lr_sk_team_…`（`api_key_auth.py:15` 正则只认 organization / department / team）。
- 平台侧会改请求：OpenAI 流式注入 `stream_options.include_usage=true`（`app/graph/nodes/routing.py:59-65`）；max_tokens 受 `permission_resolver` 上限约束（代理层直接注入点本文未核到）。无 `/v1/responses`、无 `count_tokens`。

**路线（按成本递增）**
1. 文档 + `cordis.patch.yml` 样例（格式见上游 `docs/architecture.md`）：llm-deepseek 的 baseURL / apiKey 指向平台。零代码。
2. 技能包导出多写 `.agents/skills/` 与 `.dsh/skills/`：`skills_pack_service.py:80` 现只写 `.claude/skills/<slug>/SKILL.md`；dsh 扫描根见上游 `packages/skill/skill-filesystem/src/index.ts:246-247`。
3. 个人访问令牌 `lr_sk_user_…`：`api_key_auth.py:15` 正则加 `user` scope + `mcp/auth.py::resolve_principal_from_key`（:200）新分支，让模型身份 = 工具身份；token 绑 user，角色变更即失效，才能解掉 `main.py:168` 的顾虑再挂 API-key MCP。
4. MCP 增 `search_memory`（现只有 `read_memory` 整读 / `write_memory`）。
5. 代理层归一 `max_completion_tokens` / `developer` role（`app/proxy/` 目前不处理）；DLP block 后补 `finish_reason` 终态帧，否则客户端流挂起。
6. MCP 增 `run_agent` / `get_run_result`，把 §3.2 的「后台 run + 回放」暴露给外部 agent。
7. ACP stdio 桥（上游 `packages/acp/`），dsh 作客户端接平台智能体。

**否决**：直接挂 API-key MCP（违背 `main.py:168` 吊销要求，③ 之前不做）；`/v1/responses`（上游 llm-deepseek 不用）；`count_tokens`（上游无调用方）；OAuth token 打 `/v1`（代理鉴权是 `authenticate_request` API-key 单轨，不认 JWT）。

### 改 DSH 相关代码前看这里（补 §9）

11. **循环策略只在 `dsh_runtime/src/policies.ts` 一处**。再遇到「模型只 load_skill 不干活 / 重复调失败工具 / 该停不停」，改 policies.ts 或下发 `completion_policy`，不要回到 `runner.py` / `dsh_internal.py` 加关键词（§8.2 的教训）。
12. **catalog 的 `enabled: True` ≠ 已接线**。`platform_extension_catalog.py` 只是给超管看的目录；一个包有没有生效以 `runtime.ts:99-104` 的 `ctx.plugin(...)` 为准。
13. **vendored rc.8 含 4 个 provider 但都未接线**。jsonl 持久化 / worker-thread / repeat-tool-reminder / tool-call-timeout-policy 已在 `dsh_runtime/vendor/`，要用就在 `runtime.ts::buildContext` 里 `ctx.plugin(...)`；mcp-client / subagent 仍要从上游再打包（步骤见 `VENDOR.md`）。
14. **DSH 版本号：`extensions.ts::DSH_VERSION` 一处 + 平台侧多处字面量 + `VENDOR.md` + `SHA256SUMS`**（清单见「现状·版本与包」），升级漏一处 = 扩展全部拒绝激活（`extensions.ts::verifyRelease`）或构建器误报不兼容（`builder.ts:321`）。
15. **`RunRequest` / `RuntimeEvent` 是跨语言契约**，改字段走「契约同步点」六处；`policy` 这类新事件类型要先确认 `Terminal.tsx` 对未知 type 不会抛。
16. **对外接 dsh CLI 目前只有 `/v1` 一条路**，MCP 那条被 `transport.ts:45-48`（静态 headers）× `main.py:168-170`（OAuth-only）双重锁死；不要给客户承诺「配个 URL 就能用平台工具」。
