# AI Platform 精简发布最终交接

## 范围与边界

- 任务：`PLATFORM-SLIM-E2E-20260909`
- 只修改并发布 `ai-platform` 与 `ai-platform.staging.zhuojianai.com`。
- 未修改 `aifabei-subsystem-builder`、生产协同系统、旧业务服务器或手工 `aipcopy01` 栈。
- 最终线上源码提交：`2579c2572421bc7a29e9113bd7246e45347e061a`。
- 最终 Coolify 部署：`dnkcfmcfvjqukwaeubyrpb7f`，状态 `finished`。
- 数据库 revision：`0075_retired_schema_contract`。

## 已发布修复

- 修复升级数据库遗留 `users.role NOT NULL` 导致的新建员工失败；实际权限仍只由 `UserRole` 与统一权限服务决定。
- 只把真实用户名唯一冲突返回为中文“用户名已存在”，其他数据库约束错误不再伪装成重复用户名。
- 物理删除 DSH、Connector/Data Interface、Ontology、Judge、MCP/OAuth Skill Pack、Team、ScopeManager、旧发布器、在线 Office 编辑等退役链路。
- 保留原生 Assistant Core、个人助手、业务助手、自定义智能体、工作空间、RAG、上传 Skill、Manifest Action、SSO、Runtime 与 ECS Publisher。
- 将部署收敛为 PostgreSQL、Redis、Backend、Frontend、Skill Runner、Workspace Parser、Workspace Preview、Storage Lifecycle、Multimodal Worker 共 9 个服务。
- 修复管理员和员工退出响应；真实浏览器退出后均回到登录页。
- 修复文件事件 SSE 在浏览器断开时可能把 asyncpg 连接留在未归还状态的问题：短事务在关闭数据库会话后才向客户端 yield 事件。

## 镜像与备份

- Backend、Workspace Parser、Storage Lifecycle、Multimodal Worker：`sha256:bca11b1e656032bd18ba249380ac391b8a1fa1fc8be292c3b5b40fb01d52cdef`。
- Frontend：`sha256:89a74d60eed20c220af7c9f9c08fb73e89d03023d21225d8b2288edc7eb0ca17`。
- Skill Runner：`sha256:08cac524b5a411eec2b7e0d6d8cfa265adb78427b63d64297e77a4b728a86e38`。
- Workspace Preview：`sha256:8b0de72d64704baa1c16343f706aba0d204d9fb477a12bbc1f3933584cf54921`。
- PostgreSQL：`sha256:eac621400b7b7ff52493883e41e930e3d104695fea5b68cc0c42370cf7880067`。
- Redis：`sha256:1db42cce8d57912efdafc7abda4270f062d01f91c3ac055ec70e2d9b1da0b5f3`。
- 发布前数据库备份：`/root/ai-platform-backups/20260909-slim/ai-platform-staging-pre-0074-20260909-0440.dump`。
- 备份 SHA-256：`3c9fdd596ed395c103d0ad8662c9555bde31c228574f7ff27dce6dbc5e8534ba`。

## 测试证据

### 后端语义与迁移

- 隔离 PostgreSQL/Redis 完整运行：普通套件 `524 passed`。
- 精确 PostgreSQL 18 + pgvector 0.8.2 环境：`tests/test_migration_0075_baseline.py` 为 `2 passed`。
- 两次运行合并后覆盖仓库全部 `525` 个测试节点；基线文件中的一个纯逻辑节点在两次运行中重复执行，未把它重复计数。
- 0075 验证空库只安装一个基线、Schema 指纹匹配、第二次 upgrade 无操作且 `alembic check` 零漂移。
- 文件事件 SSE 聚焦测试 `2 passed`；临时实例强制断开 25 次，连接泄漏、`CancelledError`、Traceback 和 500 均为 0。

### API 路由层

- 当前 OpenAPI 保留操作共 `322` 个。
- 隔离实例对 `322/322` 个操作逐一发起无鉴权请求；运行时失败 `0`。
- 状态分布：`200=3`、`204=1`、`401=312`、`404=3`、`422=3`。
- 该层证明路由、参数入口、认证边界和服务进程没有 5xx；它不等同于 322 个接口都完成了 staging 有状态 CRUD。
- 运行证据：`D:\Agent_Project\ai-platform-release-evidence-20260909\openapi-route-sweep-sse-hotfix.json`，SHA-256 `82FF7149F573A675009E869AA9B7DCD9DE6450764A2BDBB6670926D6134C96F1`。
- 覆盖矩阵：`D:\Agent_Project\ai-platform-release-evidence-20260909\api-coverage-matrix.json`，包含 `231` 个有静态测试引用和 `91` 个无静态引用的操作；无静态引用不代表未经过运行时 sweep。

### 真实 staging 双端浏览器

- 管理员 `root` 与员工 `zhangsan` 使用独立浏览器上下文从真实登录页进入；凭据未写入仓库、报告或 Trace。
- 两端错误密码均显示中文反馈，正常登录、刷新与真实退出通过。
- 管理员 19 个可见导航、4 个隐藏直达页面全部可达。
- 管理员预览与员工实时有效权限深比较一致；员工当前可见工作空间 18 个。
- 企业应用 iframe、Bridge 当前模块上下文通过。
- 业务助手真实生成 Excel：Artifact、OOXML、SHA-256、下载、工作空间当前版本与预览全部通过。
- E2E 唯一标记产生的 1 个 Task 已删除，1 个文件已按产品语义移入回收站；没有永久删除既有数据。
- 最终部署后再次完整执行核心脚本通过；随后 10 分钟 Backend 日志中连接未归还、连接终止、`CancelledError`、Traceback、ERROR、CRITICAL 和 HTTP 500 均为 0。

## 删除规模

以精简任务开始前提交 `c8ba2b7cd33cf9d89afe9e73f8d7306897802f78` 为基线，在本交接文档提交前：

- `275` 个文件发生变化。
- 总计新增 `14,290` 行、删除 `16,282` 行，净减少 `1,992` 行。
- Git 实际删除文件 `107` 个，其中排除文档、测试和前端测试脚本后的运行代码文件 `100` 个。
- 运行代码新增 `11,806` 行、删除 `14,247` 行，净减少 `2,441` 行。
- 删除量没有用删除测试或核心工作空间、RAG、Task、Artifact、Skill 等能力凑数。

## 验收边界

- 已完成：全部后端测试节点、全部 OpenAPI 操作的路由/认证边界 sweep，以及真实管理员/员工核心 E2E。
- 尚未宣称完成：在共享 staging 上对每个管理员实体执行一遍破坏性 CRUD、对所有 Manifest Action 逐个制造业务副作用、以及 Word/PPT/PDF/Markdown/TXT 的真实 Artifact 全格式矩阵。相应语义由完整后端测试覆盖，线上浏览器采用可恢复的核心路径，避免改动真实组织、供应商、API Key 和业务数据。
- 因此本次结论是“当前精简版本可用且已部署，核心双端路径通过”，不是“共享 staging 所有有状态操作都已逐项改写真实数据”。

## 当前状态

- staging 9 个服务健康。
- `TASKS.md` 不再保留已经完成的七天门禁或旧精简任务。
- 用户手册已按当前 9 服务和当前导航重写；历史审计交接文档仍保留旧名称仅用于追溯。
