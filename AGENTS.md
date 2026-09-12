# AI Platform 开发代理指南

## 文档定位

本文件是 AI Platform 产品边界、目标架构和工程约束的唯一事实来源。实现与本文冲突时，不得用兼容分支掩盖冲突；应先确认产品决策，再修改实现或本文。

状态定义：

- **已实现**：当前 `main` 已有并应保持工作的能力。
- **下一阶段**：目标已经确定，但代码尚未完整实现；不得对用户声称已经上线。
- **未来预留**：只有能力方向，不得提前注册为员工可用工具。
- **已退役**：没有新的明确产品决策时，禁止恢复、保留兼容入口或换名重建。

### 业务与语音收尾状态（2026-09-11）

“代码已实现”“已部署”“真实验收通过”必须分开记录，不能互相替代。

| 能力 | 代码及部署状态 | 验收边界 |
| --- | --- | --- |
| 共享 Task、导航、确认卡片、专业 AI 返回主脑 | 已有实现，沿用既有发布，不重新建设 | 既有记录不代表全部子系统均已通过 |
| 文件任务的 TTS、ASR、图片工具 | 既有 staging 发布已有实现 | 已有临时角色的文件输入验收；不代表录音按钮或所有员工已获授权 |
| 旧音频接口禁止推理字段外泄、缺失租户/主体时拒绝工作空间访问 | 已合并并部署 staging，source `9b00713` | 98 项数据库/聚焦回归通过；上线后管理员登录/空间目录、员工登录/文件视图通过 |
| 公共工具与业务候选统一相关性排序 | 已合并并部署 staging，source `9b00713` | 相关性和主脑循环回归通过；不代表全部自然语言业务场景均已验收 |
| 普通录音回填、开麦权限提示、临时录音及取消 | 已部署 staging，source `eb2e873` | 2026-09-12 候选浏览器录音→真实 OSS→ASR→追加回填通过，工作空间文件未增加，临时引用已回收；自动化音频输入不代替真人麦克风及并发取消验收 |
| 点击朗读 | 已部署 staging，source `aa2c693` | 候选真实登录、标准 TTS 播放、重复点击复用任务、工作空间不新增文件通过；线上双端登录与员工无权限提示通过，未自动授予语音权限；长回复为明确标注的节选 |
| 沉浸式轮流语音 | 可选入口已部署 staging，前端 source `6ce2a64`，manifest `29a05cf` | 已有 Task 主动开启；全局/页面复用原提交链路。合成浏览器完整回路通过，线上员工开麦/退出释放通过；真人麦克风与真实子系统语音操作未验收。切换页面/视图安全退出语音，保留对话 |
| React 19 静态消息/确认弹窗兼容 | 已部署，前端 source `4c7dfb6` | 候选消息、通知、确认取消通过；线上 zhangsan 点击录音显示中文无权限提示且不开麦，无角色变更 |
| 未知写入受控核实、历史运行 401 排查 | 本轮待收尾 | 未取得证据前不得声称解决 |

语音交互复用同一 Task：普通录音经 ASR 后回填可编辑输入框；默认回复不自动朗读；用户点击朗读或主动开启沉浸式模式后才调用 TTS。已有音频文件工具继续处理明确的转写或生成 MP3 任务。

沉浸式第一版采用轮流对话，播放期间停止采集；退出、登出和刷新不得自动开麦或补播历史回复。业务写入仍必须点击可信确认卡片。普通录音和朗读使用受控临时媒体，用户要求保存时才提交工作空间 Artifact。语音失败不得重跑已经成功的业务操作。

## 产品定义

AI Platform 是企业 AI 控制平面：

```text
企业身份与角色鉴权
+ 模型能力网关
+ 统一 AI Assistant Core
+ 工作空间、OSS 与 Artifact 交付
+ 企业子系统接入与业务 Action 执行
```

平台不是独立业务系统、RAG 产品或插件市场。业务记录、流程、表单和待办保留在已登记的子系统中。

员工只看到一个“灼见助手”。全局主页和子系统页面侧栏只是同一个助手在不同上下文中的两个视图，不是个人助手与业务助手两套产品。

## 当前能力与目标状态

### 已实现并保留

- 企业、部门、员工、角色、权限和审计。
- 模型供应商、模型部署、模型路由和 OpenAI/Anthropic 兼容接口。
- 原生 Assistant Core、Task、消息、运行事件、SSE 和文件 Artifact 基础链路。
- 工作空间、文件版本、OSS 对象引用、预览、下载、回收站和生命周期服务。
- 受控 Excel、Word、PowerPoint、PDF、文本与部分媒体工具。
- 子系统 Runtime、Manifest、Action、Event、SSO、Bridge 和 ECS Publisher。
- 管理员端、员工端、用量核算、安全和轻量运维监控。

### 下一阶段实现

- 全局主页与页面侧栏共享一个 Task、历史、目标、文件引用和 Artifact 流。
- 角色过滤的企业能力目录、动态工具发现和统一工具描述协议。
- 供应商无关的视觉/OCR、生图、ASR、音频理解和 TTS 稳定工具。
- 可选的子系统专业 AI 作为统一主脑的内部工具，而不是第二套用户助手。
- 导航、确认卡片和 Bridge 局部刷新形成统一交互闭环。

### 未来预留

- 视频理解和视频生成。未完成模型验证、工具协议和 Artifact 验收前，不注册为主脑工具，也不在员工端宣传。

### 已退役

- 知识库/RAG、向量索引、Embedding 和 Reranker。
- 平台内用户 Skill 上传、安装与执行，任意代码 Skill Runner，以及智能体专属 Skill 绑定。
- DSH Runtime、市场、外部扩展和扩展构建器。
- Connector、Tool Endpoint、Data Interface/Data System 和应用工具绑定抽象。
- Ontology、Judge、MCP/OAuth Skill Pack、Team 和 ScopeManager。
- 旧模块发布器、在线 Office 协作编辑和两套独立助手运行时。

外部 `aifabei-subsystem-builder` 是子系统接入契约，不属于已经退役的平台内“用户 Skill”，不得混淆。

## 权限唯一事实来源

- 管理员统一在“角色权限”页管理角色与语音/平台能力；旧 `/org/roles` 页面已删除。2026-09-12 已部署 source b3057dc，线上管理员入口验收通过。语音不默认授予全员，也不直接授予员工；`*` 角色继承全部平台能力。用户明确要求后，zhangsan 已绑定企业管理员并通过线上朗读验收。

- 身份认证只确定当前员工是谁。用户身份用于登录、会话、审计归属和个人资源所有权，不直接产生业务权限。
- SaaS 页面、子系统页面、Manifest Action、业务数据和工作空间访问均只由员工当前绑定的有效角色决定。
- 一个员工可绑定多个角色，最终权限取角色并集；但 Action 权限与数据范围必须保持在授予它的同一角色内，禁止把角色甲的数据范围与角色乙的操作权限拼成更大权限。
- 部门只是组织结构属性，不得自动授予页面、Action、业务数据或部门工作空间权限。
- 禁止直接给用户授予业务权限、部门兜底授权和按用户名编写特例。
- 企业管理员的 `*` 和平台超级管理员能力也必须表达为角色权限；管理界面准确显示计算后的有效权限。
- SaaS API、工作空间、Assistant 工具、Manifest Action、SSO claims、Bridge 上下文和子系统鉴权必须复用同一角色权限计算结果。
- 角色绑定或角色权限变化必须递增 `auth_epoch`；下一次请求重新计算权限，旧 claims、页面缓存和工具目录不得继续访问。

## 统一助手目标架构

```text
统一助手 Task / Session
├─ 对话、目标、工具结果、业务对象和文件引用
├─ 动态工具目录
│  ├─ 企业能力搜索与导航
│  ├─ 平台公共工具
│  ├─ 模型能力工具
│  ├─ 工作空间和文件工具
│  └─ 当前角色获权的子系统 Action
├─ 工作空间
│  ├─ 用户引用的输入文件
│  └─ AI 生成并交付的 Artifact
└─ 子系统
   ├─ 模块、页面和能力说明
   ├─ 结构化业务 Action
   └─ 可选的内部专业 AI
```

- Task 保存对话、目标、事件、文件与 Artifact 引用，不保存大文件字节。
- 全局主页和页面侧栏复用同一 Task；打开页面、关闭侧栏、刷新或返回主页不得创建第二段对话。
- Task 不永久绑定首次进入的应用。切换页面只更新本轮上下文，并继续未完成目标。
- 不把整个企业能力目录、全部 CRUD 工具或整个工作空间塞进模型上下文。
- “总业务 AI”和“页面业务 AI”只表示同一主脑的上下文状态：前者负责发现与导航，后者额外获得当前页面精确 Actions。

每轮由服务端生成并校验 `AssistantTurnContext`：

```text
taskId
applicationId?
moduleKey?
pageKey?
businessObjects[]
roleIds[]
authEpoch
referencedFiles[]: fileId + versionId
pendingGoal?
```

模型不得自行填写或更改身份、角色、权限范围、应用、页面或工作空间 ID。业务意图分类只可辅助工具检索，不得成为执行门禁，也不得在尚未尝试工具前直接回复“目标不明确”。

## LLM 主脑与工具循环

LLM 负责理解、规划、展示和选择工具；确定性执行层负责权限、参数、确认、幂等、真实副作用、输出验证和审计。系统提示词保持短小，不用大量 `if/else` 预判自然语言。

```text
用户自然表达
→ 主脑结合当前页面、业务对象和历史理解目标
→ 搜索企业能力或选择平台能力
→ 动态加载严格工具
→ SaaS 校验角色和参数
   ├─ 合法：执行
   └─ 可修正：返回错误字段、原因、合法格式和候选值
→ LLM 自动纠正并继续调用（首次尝试后最多三次纠正，受整轮超时和步骤上限约束）
→ LLM 决定确认、导航、继续调用或回答
→ 结果和 Artifact 写回同一 Task
```

- 用户无需说系统名、模块名或 Action 名；工具名称、描述和示例使用用户会说的业务词汇。
- 能从页面上下文、业务对象或查询工具获得的信息，主脑先自行查询；多个实质候选仍无法判断时才询问用户。
- 模型或协议错误属于平台错误，不得改写成“用户表达不清”。
- 可修正参数错误允许自动重试；权限不足、确认拒绝和不可恢复冲突不得换工具绕过。
- LLM 不得编造权限、凭证、目标地址、工具结果、文件路径或 Artifact。
- 只展示可验证进度，例如“正在查找款号资料”“等待确认”“正在保存文件”，不得展示模型私有思维链。

## 唯一工具描述协议

内部工具统一使用 `AssistantToolDescriptor`：

```text
name
description
inputSchema
outputSchema
riskLevel
requiredRolePermissions
requiredContext
modelCapabilityBinding
idempotencyPolicy
confirmationPolicy
artifactPolicy
```

统一返回 `ToolResultEnvelope`：

```text
status: completed | needs_input | needs_confirmation | retryable_error | failed
data
artifacts[]
uiIntent
error:
  code
  messageZh
  correctionFields
  retryable
```

- 输入输出必须是严格 Schema；供应商支持时开启严格工具调用，SaaS 服务端始终二次校验。
- 工具只返回结构化事实、候选、回执和 Artifact；最终表达由统一主脑完成。
- `uiIntent` 只能表达受控导航、确认卡片和局部刷新，不能携带任意前端代码。

## 企业能力导航与动态工具目录

从已批准 Manifest 生成角色过滤后的能力目录，包含系统、模块、页面、业务实体、可回答问题、可执行动作和导航目标。主脑常驻入口保持很少：

```text
enterprise_capability_search
enterprise_navigate
workspace_search
```

其余工具按需加载：

```text
用户自然语言
→ 在当前角色可用能力目录中检索
→ 返回最相关的少量工具摘要
→ 加载本轮需要的完整 Schema
→ 主脑选择并调用
```

- 能力搜索只返回少量候选；选定页面后才加载准确 CRUD Schema。
- 目录只包含当前角色可用能力，不先把无权工具交给模型再依赖执行时拒绝。
- 缓存至少按企业、角色集合、`authEpoch`、Manifest 版本、页面和模型能力状态隔离。
- 角色、Manifest 或模型部署变化时立即失效缓存。
- OpenAI 适配器使用 `allowed_tools` 或等价限制；Anthropic 可延迟加载工具；其他供应商由 SaaS 先检索再只发送工具子集。
- 同名工具必须带有明确应用、页面和业务语义，禁止跨系统误选。

## 模型供应商、模型部署与稳定工具

固定关系：

```text
模型供应商
→ 经管理员验证的模型部署
→ 平台标准 capability
→ 主脑可见的稳定工具
```

| 标准能力 | 主脑可见能力 | 状态 |
|---|---|---|
| `chat` | 主脑本身，不注册为工具 | 已实现 |
| `vision` | `image_tool`：理解、OCR、比较、分类 | 下一阶段统一 |
| `image_generation` | `image_generation_tool` | 下一阶段统一 |
| `speech_to_text` | `audio_transcribe` | 下一阶段实现 |
| `audio_understanding` | `audio_understand` | 下一阶段实现 |
| `text_to_speech` | `speech_synthesize(mode=standard)` | 下一阶段实现 |
| `voice_design` | `speech_synthesize(mode=design)` | 下一阶段实现 |
| `voice_clone` | `speech_synthesize(mode=clone)` | 下一阶段实现 |
| 视频能力 | 不注册 | 未来预留 |

- 管理员配置供应商协议、Base URL、密钥、模型部署、适配器、作用域和优先级。
- 每项 capability 必须经真实请求验证后才能进入路由，不能根据模型名称自动声明。
- LLM 调用稳定工具时不能指定供应商、模型 ID、API Key 或任意服务地址。SaaS 根据 capability、作用域、启停、验证状态、健康状态和管理员优先级选择部署。
- 同一 capability 可有多个供应商部署；故障时只降级到相同能力。
- 一个工具对应一种稳定能力，不对应某个供应商；管理员更换供应商后，助手、子系统和 Artifact 协议保持不变。
- 文件处理、Web、工作空间和业务 Action 是平台工具，不伪装成模型能力。
- 没有原生音频理解部署时，主脑可显式执行“ASR → 分析转写文本”，不得伪装成原生音频理解。

下一阶段真实验收候选：

- 小米 MiMo：`mimo-v2.5-pro`、`mimo-v2.5`、`mimo-v2.5-asr`、`mimo-v2.5-tts`、`mimo-v2.5-tts-voicedesign`、`mimo-v2.5-tts-voiceclone`。
- 阿里云百炼：使用管理员已配置并验证的图像生成部署。

候选名称只用于测试计划，不表示已经注册或健康。对支持 `reasoning_content` 的模型，多轮工具调用按供应商协议回传必要字段，但不得把私有推理内容展示给用户。供应商临时文件 URL 必须转存平台 OSS，不能直接作为最终产物。

## 工作空间、OSS 与 Artifact

工作空间是统一助手的受控文件系统，不是聊天记忆，也不是 RAG。总入口、页面侧栏和子系统专业 AI 通过同一组 `fileId + versionId` 连续协作。

用户上传链路：

```text
角色权限校验
→ Storage Gateway 生成短时上传签名
→ 浏览器直传 OSS
→ 服务端校验对象、类型、大小和哈希
→ 创建工作空间文件与版本
```

AI 产物链路：

```text
LLM 调用平台工具
→ 临时沙箱或模型服务生成结果
→ 格式、安全和哈希校验
→ 再次校验目标工作空间角色权限
→ Storage Gateway 上传 OSS
→ 数据库提交文件版本
→ 持久化 Artifact
→ 同一助手展示预览/下载卡片
```

读取链路：

```text
fileId + versionId
→ 实时角色鉴权
→ Storage Gateway 生成短时预览或下载地址
→ 浏览器读取
```

- 数据库只保存文件元数据、版本、权限、校验值和 `oss://` 引用；OSS 保存文件字节。
- OSS 长期密钥只由 Storage Gateway 持有；用户、LLM、浏览器和子系统均不得获得。
- 聊天和 Artifact 只保存稳定 `fileId/versionId`，不得保存长期签名 URL。
- 每轮只读取用户明确引用、任务需要或 `workspace_search` 命中的文件，不静默扫描整个工作空间。
- 默认输出到员工个人空间；指定共享空间时按当前角色校验写入权限。
- AI 修改携带源文件 `fileId + baseVersionId`，结果另存为新文件，原件及其版本不变；源版本变化时拒绝提交。网页只提供预览和下载，不提供手工文档编辑。
- 删除对话只删除 Task 和引用，不删除工作空间文件；删除文件先进入回收站，无有效引用后由生命周期服务清理 OSS。
- 权限在读取、修改和最终提交时分别重查；运行中撤权后不得提交产物。
- 子系统业务附件归子系统；SaaS AI 临时文件和最终产物只能进入工作空间，禁止写入子系统 ECS。

文件型任务只有工作空间事务成功且 `artifacts` 非空时才允许标记 `completed`。工具成功但 OSS 上传、版本提交或 Artifact 持久化失败时，整轮失败，正文不得宣称文件已经生成。

## 子系统是统一助手的业务能力包

```text
子系统 Manifest
├─ 系统、模块、页面和业务实体说明
├─ 可回答问题和 Action 名称及用途
├─ 输入/输出 Schema
├─ 风险与确认要求
└─ 受控导航/刷新目标
```

```text
统一助手定位能力
→ SaaS 检查当前角色权限
→ 加载对应 Manifest Action
→ LLM 生成参数
→ SaaS 校验、确认并执行
→ 结构化结果返回同一 Task
→ 必要时导航或局部刷新页面
```

- Manifest 名称、描述和示例只用于能力检索，并视为非可信业务数据，不能覆盖 SaaS 系统规则或扩大权限。
- 子系统只接收执行所需参数、业务身份和短时凭证，不能看到完整对话、完整工作空间或其他系统工具。
- 工作空间文件作为 Action 输入时必须由 Schema 明确声明；SaaS 提供短时受控读取，不交付 OSS 密钥。
- 子系统 Action 返回结构化业务结果，不返回服务器路径、假下载地址或虚假 Artifact。
- 子系统业务数据需要生成文件时，由 SaaS 文件执行器写入用户工作空间。
- 页面按钮与 AI 确认卡片必须调用同一业务 Action。

## 可选的子系统专业 AI

只有确实需要领域推理的模块才声明专业 AI。它是统一主脑可调用的内部工具或连接代理：

```text
统一主脑
→ subsystem_specialist（最少业务上下文、相关文件和目标）
→ 专业执行器返回结构化分析
→ 统一主脑决定后续 Action、文件和用户回答
```

- 专业 AI 不拥有独立聊天框、Task、工作空间、长期记忆或模型密钥。
- 只接收相关对话摘要，不复制全部历史；只能使用显式授权的当前子系统能力，不能横跨应用。
- 专业 AI 不直接向用户发送最终回复，结果必须返回统一主脑。
- 专业 AI 仍通过 SaaS 模型网关调用管理员配置的模型。
- 专业 AI 产物仍由 SaaS 通过工作空间 Artifact 链路交付。

## 导航、确认卡片与页面反馈

- 查询、分析和可在后台安全完成的任务不强制跳转；完成后可提供“打开查看”。
- 用户明确说“带我去”，或必须查看页面、选择字段、填写复杂信息时才导航，并继续原始目标。
- 新增、修改、删除、提交等副作用使用 SaaS 确认卡片。卡片携带稳定 Action 引用、规范化参数和修改前后值，前端不得从 LLM 文本解析按钮。
- 用户确认后才执行；取消后不产生业务副作用。
- 执行成功后通过 Bridge 发送受信任的局部刷新事件，禁止整体重载 iframe 或让用户看到闪屏。
- 子系统可声明刷新和导航目标，但不得返回任意可执行前端代码。

## 错误恢复、幂等与完成条件

- Schema 错误返回具体字段、原因、合法格式和候选值，供 LLM 在首次尝试后最多自动纠正三次。连续两次完全相同的错误调用应停止原样重试，改换方法或澄清；以最终任务完成验收，不以首次调用成功验收。权限不足、取消、版本冲突和危险参数不能通过纠错绕过；写操作超时先核实执行状态，不盲目重发。
- 业务对象不存在时允许主脑继续查询；多个对象匹配时让用户选择。
- 权限不足立即终止相关工具链，不允许借其他页面、角色或子系统绕过。
- 相同 `runId + toolCallId` 必须幂等，不重复产生业务副作用、OSS 对象或 Artifact。
- SSE 重连通过持久化事件恢复，文件卡片按 `fileId + versionId` 去重。
- 完成状态只由确定性执行结果决定，不能由模型正文中的“已完成”决定。
- 供应商故障、能力缺失和路由失败返回中文可理解提示。

## 实施验收重点

- 使用自然表达测试，不要求用户说出系统、模块或 Action 名。
- 回归“调用 204A231 款资料”“204A231 款图片”“把这个订单负责人改成李娜”等已知失败语句。
- 验证总入口和页面侧栏共享 Task、历史、文件、业务实体和未完成目标。
- 验证工具检索只加载少量相关工具，不误选其他系统同名 Action。
- 验证参数错误自动纠正，无法纠正时才询问用户。
- 验证个人空间、共享空间、版本冲突、回收站和运行中撤权。
- 验证 MiMo 主脑多轮工具调用及必要 `reasoning_content` 回传。
- 真实验证 MiMo 图片理解、OCR、ASR、标准 TTS、音色设计和声音克隆，以及阿里云生图与异步 Artifact 交付。
- 使用 `root` 验证供应商、部署、能力测试、角色授权和审计；使用 `zhangsan` 验证自然语言、导航、业务 Action、确认卡片、工作空间和 Artifact。

## 研究依据

本架构采用“LLM 生成式编排 + 确定性权限/确认/执行”，将会话状态与大文件 Artifact 分开，并按轮加载少量工具。优先参考以下官方资料：

- [Microsoft：生成式编排](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/generative-orchestration)
- [OpenAI：Function Calling 与严格工具 Schema](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI：Allowed Tools / 按轮限制工具集合](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.2)
- [Anthropic：Tool Search / 延迟工具加载](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Google ADK：Session](https://adk.dev/sessions/)
- [Google ADK：Artifact](https://adk.dev/artifacts/)
- [Google ADK：Context](https://adk.dev/context/)
- [Microsoft：Connected Agents](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/authoring-add-other-agents)
- [小米 MiMo：多轮推理字段回传](https://platform.xiaomimimo.com/docs/en-US/usage-guide/passing-back-reasoning_content)
- [小米 MiMo：V2.5 语音能力](https://platform.xiaomimimo.com/docs/en-US/news/previous-news/v2.5-tts-release)
- [阿里云百炼：图像模型](https://help.aliyun.com/zh/model-studio/image-model)
- [阿里云百炼：文生图](https://help.aliyun.com/zh/model-studio/text-to-image)

## 架构目录

- `llm_router/backend/app/`：FastAPI 后端，包含认证、角色权限、模型路由、助手、工作空间和子系统集成。
- `frontend/src/`：React/TypeScript 管理员端和员工端。
- `tool_executor/`：隔离执行已审核的平台固定工具，禁止运行用户代码。
- `docker-compose.coolify.yml`：Registry-first staging 部署清单。
- `llm_router/backend/alembic/versions/`：唯一数据库迁移链。

## 开始工作

- 修改前完整阅读本文件、`TASKS.md` 和 `docs/handoff/` 中的最新交接记录。
- 每个代理使用独立 Git worktree，禁止直接在 `main` 上工作。
- 修改产品代码前，在 `TASKS.md` 认领任务并提交认领；纯文档审查不占用产品代码单航道。

## 常用命令

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

在 `llm_router/backend` 使用 `pytest tests/<file>.py -q` 运行聚焦后端测试。使用对应的 `npm run test:*` 脚本运行前端契约测试。

## 硬边界

- SaaS 负责身份、角色授权、模型路由、统一助手、工作空间、Artifact 和可审计的集成调用。
- 业务记录、流程、表单和待办保留在已登记子系统中。
- 禁止暴露密钥、数据库端口、Docker API 或不受限制的服务器路径。
- 权限变更必须同时测试允许路径和拒绝路径。
- 数据库变更遵循 expand/migrate/contract；发布时验证上一版镜像仍兼容。
- 源码提交完成测试且 Registry 返回新 digest 前，禁止修改部署镜像 digest。
- 禁止提交 `.env`、Token、密钥、数据库备份、生成产物或本地工具配置。

## 标准变更流程

1. 获取最新 `origin/main`，创建专用分支和 worktree。
2. 修改前检查受影响调用链和数据库迁移。
3. 完成最小且完整的一组修改，并增加聚焦测试。
4. 按影响范围运行 `git diff --check`、聚焦测试、后端 lint 和前端构建。
5. 在 `docs/handoff/` 写交接文件，并从 `TASKS.md` 删除已完成任务块。
6. 只暂存明确文件，审查暂存差异，再使用约定式提交并添加 `Co-Authored-By: Codex <codex@openai.com>`。
7. 禁止强推；重新变基或合并最新 `origin/main`，重跑测试后再发布。

## 并行协作

- 数据库迁移链、身份认证、角色权限和 CI 属于 `@ZhuoJian-AI/developers` 管理的单航道区域，同一时刻只能由一个任务修改。
- 保留无关用户修改，禁止 stash、丢弃、reset 或 clean 其他贡献者的工作。
- 交接必须记录范围、行为变化、准确验证命令与结果、剩余工作、风险和决策。

