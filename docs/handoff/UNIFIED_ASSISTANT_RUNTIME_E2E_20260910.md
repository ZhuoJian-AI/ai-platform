# 统一助手运行验收续接

## 已核实

- 基线为 `df2301c`，独立分支 `fix/unified-assistant-runtime-e2e-20260910`。
- `_build_tools` 构建全部获权注册表；`_consume_native` 在调用模型前通过 `partition_tool_specs` 分为常驻和延迟工具；原生循环在能力搜索成功后才加载命中的工具。
- 先前根据“本轮授权工具集合”推断全部工具都发给模型的判断不成立。该事件记录的是分组前目录，不能作为供应商请求证据。

## 本次修改

- 分组前事件明确标注包含待加载工具。
- 分组后增加首次模型请求实际工具名称与延迟数量事件。
- 动态加载事件记录新增工具和当前可见工具。
- 回归测试将事件中的可见工具与模拟网关实际收到的工具比较。

## 验证

- `pytest tests/test_native_assistant_core.py tests/test_assistant_tool_catalog.py -q`：21 passed。
- `ruff check app/agents/core/runner.py app/agents/core/native.py`：通过。
- 未部署本次修改；上述测试使用模拟模型，不代表真实供应商和浏览器端到端完成。

## 继续工作

- 已修复能力测试失败状态回滚：负面验证返回 HTTP 400 响应而不抛出事务异常，保留失败状态及脱敏错误分类。新增测试经过真实 `get_db` 生命周期，但事务存储为测试替身，仍需 PostgreSQL/HTTP 端到端复验。
- 聊天验证预算由 128 调整为 512，与视觉验证一致；没有最终正文仍拒绝验证。
- 聚焦网关、原生循环和目录测试：25 passed。当前 Docker Desktop 引擎未运行，尚未重跑 PostgreSQL 集成测试。
- 新增 `test_failed_verification_survives_http_request_and_new_db_session`：使用真实 HTTP、生产事务依赖和新数据库会话校验状态持久化。实际执行在 fixture 建连阶段因 WinError 1225 失败，未到测试正文，不计通过。尝试启动 Docker Desktop 后引擎仍不可用；`docker pull postgres:16` 也因 Linux engine 管道不存在而失败。下一轮先恢复一次性 PostgreSQL 环境或使用已授权隔离测试数据库，再执行该测试。

- 核对模型能力测试失败状态持久化、MiMo 多轮调用和全部语音模式。
- 完成真实管理员与员工双端、OSS 文件交付、权限撤销、确认取消和跨视图接力测试。
- 平台完整目标尚未完成；禁止仅凭本次测试发布完成结论。

## 2026-09-10 19:24 真实员工语音负面验收

- 通过员工登录表单认证，未伪造 Token/Cookie；创建专用任务 `71b072f1-1d5a-4299-af3a-dc1651d50092`，要求生成个人空间 MP3。
- 实际运行进行了多轮能力搜索，没有调用 `speech_synthesize`，最终创建 `E2E-20260910-voice-配音脚本.txt`，界面显示“部分完成”。本项 MP3 交付验收失败，文本不是用户要求的音频。
- 使用登录后会话只读查询 `/api/v1/terminal/me`：当前角色并集不含 `multimodal.speech.use`、`multimodal.audio.transcribe` 或 `multimodal.audio.understand`。源代码 `model_capability_availability` 要求对应权限后才装配工具，因此不能根据搜索失败断言平台没有 TTS。
- 待修复/复验：不可用能力的解释不能误报为平台未接入；不能主动用无关文本文件替代 MP3；需要管理员临时测试角色授权后的成功路径与撤权拒绝路径。该任务生成的测试文本和测试记忆须在验收结束清理，不清理用户其他文件或记忆。
- 同次重新执行聚焦测试：`pytest tests/test_model_gateway_contract.py tests/test_native_assistant_core.py tests/test_assistant_tool_catalog.py -q`，25 passed。
- 本地 PostgreSQL 仍未启动：Docker Desktop 日志明确为残留 `dockerInference` reparse 节点不可访问导致 Inference manager 初始化失败。尝试可恢复移动该单一节点被 Windows 拒绝，没有删除任何节点、容器、数据卷或重置 Docker。下一步可使用独立 PostgreSQL 运行环境，不必继续重复启动失败的 Docker。
- 部署规则重新获取为 `c948cd2`；本轮没有部署。

## 2026-09-10 19:34 管理员—员工语音权限闭环

- root 真实表单登录后，通过 `/org/roles` 创建 `E2E-20260910-语音能力`（code `e2e_20260910_audio`），包含转写、音频理解、朗读、设计和克隆五项权限；通过员工编辑表单附加给 zhangsan，保留原三个角色。
- 授权后旧员工会话调用 `/api/v1/terminal/me` 返回 401 `User session has been revoked`。重新表单登录后，me 返回上述五项权限，证明角色变更与新会话权限生效。
- 同一 Task 续问重新生成 MP3，仍未发现语音工具。只读调用 `/api/v1/multimodal/voices` 返回 404 `Multimodal audio is not enabled for this organization`。因此除了原来的权限缺项，还存在已部署环境的组织语音开关阻断；不能仅启用模型部署后就宣称助手可用。
- 第二轮最终未生成文件，出现连续八次 `web_tool` 失败，直到第 19 步才结束。还需修复缺少能力时的可解释终止及重复失败控制，不能只扩大重试上限。
- 第一轮 TXT 替代 MP3 的结果，实时显示“部分完成”，刷新后变为“已完成（有重试）”。`TerminalAssistantMessage.verificationFromBlocks` 依据任意 Artifact 和末次失败后的工具成功推断 recovered，不能证明用户目标完成；需与服务端可信交付状态统一，不能仅改提示词。
- 已经通过管理员 UI 撤销临时角色，员工行重新显示原来的总经理、production01、系统研发者；随后删除临时角色并确认列表不存在该记录。未修改任何原有角色权限。
- 尚未修改语音部署开关，没有部署本地代码；下一步核对实际 Coolify 配置并修复交付/失败控制，再进行授权后的真正 MP3 成功验收。

## 原生循环重试上限修复

- 原先仅按完整参数哈希计数，改变参数即可绕过重复失败控制。现在增加本轮每个工具的失败计数：首次失败后允许两次修正，三次仍失败则移出后续模型工具集合。其它工具保留，该工具真实成功才清零其计数。
- 同一模型批次中已经排队的后续调用也会收到 `tool_retry_exhausted`，不会继续触发执行器。动态能力加载重建工具集合时继续排除已停用工具。
- 批量工具结果全部追加完毕后才追加恢复提示，避免在 assistant tool_calls 与尚未返回的 tool 消息之间插入 user 消息导致供应商协议错误。
- 新增改变参数、批量绕过、成功清零与批量消息顺序测试。聚焦测试 28 passed；Ruff 通过。此结果为模拟网关单元测试，不替代待完成的线上复验。

## 文件交付状态误报修复（本地，未发布）

- 服务端历史消息分类和前端即时分类不再通过“任意 Artifact + 失败后任意成功工具”推断 recovered。工具调用统计只能证明执行记录，不能证明用户要求的文件已交付。
- 新增 TaskMessageRead 回归：语音失败、文本创建成功和读取成功，即使存在稳定 TXT 文件版本，刷新后的分类仍为 partial，不升级为完成。
- `pytest tests/test_message_verification.py tests/test_native_assistant_core.py tests/test_assistant_tool_catalog.py -q`：35 passed；对应 Python 文件 Ruff 通过。
- 安装当前工作树锁定依赖后，`npm run build` 通过；保留现有大 chunk 与 stream externalized 构建警告。`npm run test:file-ui`、`npm run test:presentation` 通过。
- 此修复只消除缺少证明时的完成推断。运行时 `_tool_result_has_trusted_artifact` 仍只验证稳定文件/版本身份，尚未校验请求目标格式；下一步必须补齐目标交付约束和最终持久化状态，再完成真实 MP3 正向交付、历史恢复以及完整模型验收。不得将本次聚焦测试当作全目标完成。

## 原生循环无产物终止语义（本地，未发布）

- 发现 completion policy 重试用尽后仍可 yield done，即使没有 fileId/versionId。现在文件任务无交付时直接返回 ARTIFACT_DELIVERY_FAILED；runner 已将 error 事件转换为 AssistantRunError，进入现有失败持久化路径。
- 新增零、一、两次纠正预算测试，断言无产物绝不发出 done。修正旧正向测试夹具：只有 file_id 没有 version_id 不是真实交付，正向夹具补齐版本；服务器路径负向测试改为断言明确失败。
- 同跑发现 policy 测试误把新增工具目录 trace 当作 policy trace，已按 category 筛选，仍核对全部 policy 事件及顺序。
- `pytest tests/test_native_assistant_core.py tests/test_assistant_policy.py tests/test_message_verification.py -q`：56 passed。对应三个 Python 文件 Ruff 通过。
- 目标格式匹配、成功交付验证和 staging 双端全量回归仍未完成。本轮不部署，不修改 Skill、业务子系统或配置。

## 2026-09-10 19:58 隔离 PostgreSQL 与实际配置复核

- 依据部署规则 c948cd2，只读核对当前 SaaS 主栈：9 个服务 healthy。当前 backend 的 MULTIMODAL_AUDIO_ENABLED 实际为 false，allowlist 为爱法贝组织 UUID；未修改这些配置。
- 本地 Docker 故障不再阻挡数据库验证：在 SaaS 主机创建本任务专用临时 PostgreSQL 容器 ai-platform-e2e-pg-20260910，复用已缓存 PostgreSQL 镜像；仅绑定 127.0.0.1:55439，经 SSH 隧道访问，内存盘保存纯测试数据，不挂载 staging 数据卷。
- TEST_DATABASE_URL 和 DATABASE_URL 均显式指向隔离测试库。执行 `pytest tests/test_model_gateway.py::test_failed_verification_survives_http_request_and_new_db_session -q`，1 passed，112.64 秒，含建表和清理。
- 此项证明真实 PostgreSQL、HTTP 请求和新事务会话下，失败能力验证状态能够持久化；上游仍为测试替身，不能当作 MiMo 或全模型 E2E 验收通过。
- 测试结束后核对容器任务标签，停止并自动删除该临时容器及内存盘，终止 SSH 隧道；未删除真实文件、数据库或其他项目资源。源码未部署。
- 后续大量数据库用例宜在隔离环境本机执行，避免每次 ORM 建表/清表通过公网隧道造成延迟。仍须补齐格式交付、实际模型与双端完整验收。
