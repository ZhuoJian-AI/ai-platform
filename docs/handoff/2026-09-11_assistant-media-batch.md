# 统一助手媒体与写操作持久回执收尾

## 范围

- 只修改 AI Platform。沿用部署规则 c948cd2，不修改外部 Skill、子系统、数据库 Schema 或其他项目。
- 默认模型未手选时交给既有默认路由，不再在 LLM 调用前返回 400。明确选择模型仍做实时可用性检查。
- 工具检索优先匹配具体操作，能力组别名只辅助召回；页面加分不再让完全不相关的 Action 入选。
- 图片/音频模型只接受实际回答，不把 reasoning_content 当最终结果。空回答返回可恢复错误。
- 语音通过 FFmpeg 完整解码后才能验证或提交；音色设计支持描述，克隆仍要求授权音色。失败能力验证持久撤销对应路由资格。
- 图片和语音在 OSS 上传前后重查角色/工作空间权限；撤权时回滚版本并清理本轮上传对象。生图回执补齐文件版本、哈希和大小。
- 写 Action 先提交执行日志再发送 HTTP，以 PostgreSQL 事务锁保护相同操作的并发准入。进程取消后仍保留未知回执；远端成功回执也独立提交，后续对话失败不会丢失。

## 验证

- `python -m pytest --noconftest tests/test_terminal_default_model.py tests/test_action_unknown_outcome.py tests/test_model_capability_tools.py tests/test_model_gateway_contract.py tests/test_image_artifact_receipt.py tests/test_image_route_verification.py tests/test_assistant_tool_catalog.py tests/test_analysis_evidence.py tests/test_native_assistant_core.py tests/test_hybrid_rbac_audio.py -q`：181 passed。这些为隔离单元测试；不冒充数据库全量集成测试。
- 默认 conftest 运行因本机 localhost:5434 无 PostgreSQL 在 fixture 阶段失败，未据此修改业务代码。
- 真实 PostgreSQL 随机临时库验证跨会话未知日志、并发确认只发一次、HTTP 期间取消仍保留日志；临时库测试后删除，不修改业务记录。
- 修改文件 Ruff 与 `git diff --check` 通过。
- 候选环境使用现有隔离 ai_infra_candidate 数据库，真实管理员表单登录确认模型部署；真实员工浏览器完成如下链路，无注入 Cookie/Token 登录：
  - 标准 TTS → 工作空间 → 刷新 → 下载哈希一致；Task `b388e4c2-590e-4ec0-8f41-73286d65e3f1`，file `82b06f2f-daeb-4574-b5fa-b7e14e8b0609`。
  - 同 Task ASR 转写前述音频，正确识别 100 件、3 个缺陷，无多余 Artifact。
  - 音色设计 → 工作空间 → 刷新下载；Task `25c41111-ed18-4016-8097-41fd67c49426`，file `60abd256-a79f-4317-8a4d-36e195748142`。
  - 阿里云生图 → 工作空间 → 刷新下载；Task `328165c5-03f6-4191-8f8b-f740e4961eac`，file `05a4bbf3-494e-462e-b2ed-905a0181e719`。
  - 同 Task 识图读取上一步真实图片，识别蓝色衣服，无多余 Artifact。
- 复用此前已通过的真实子系统共享会话、导航、确认 CRUD、专业 AI 回主脑与 AI 修改另存证据，不重复全量验收。

## 限制与发布状态

- 候选配置未声明原生 audio_understanding，voice_clone 未验证；不能宣称这两项可用或暗中降级。
- 本批不提供远端未知写入状态的自动核实/解锁。没有可信结果前继续阻止相同写入，不按超时放行；不同参数的语义重复不在本批保护范围。
- 首次工具失败只要恢复并完成即通过；没有真实产物不得报完成。没有增加所有错误都致整轮失败的规则。
- 当前文件记录的是候选验收；发布后的 source/manifest/digest、健康和员工回归另补，不将候选结果写成 staging 已上线。

## 已发布及 staging 差异

- source `a7a2e0fd1d7a876c7dcb8488edb9395940b6a3b2`（PR #114）；manifest `a6baed957c3acffaef67827653f06e3446f8da9e`（PR #115）。
- backend `sha256:84032ed2ee9a9c408385c2b0b937060fe6a7b26ec447416a55f10dde21f2749f`。Registry 200；源文件与镜像 LF 归一化哈希一致，git archive 的 Windows CRLF 只改变换行。
- 首次部署 `media84b5dada7be50dc7` finished；九服务 healthy，公网 `/health` 200；OCI source、digest、共享 Executor/Storage Token 一致性验证通过。旧 backend `43f7449...` 保留。
- root 真实浏览器登录及供应商/模型配置读取通过。前端镜像不变；无数据库迁移，因此不做数据库备份。
- staging 首次 TTS Task `0326525c-2858-4ef9-aef1-78732aa6ec3f` 被实际角色权限过滤：zhangsan 原角色没有 multimodal 语音权限。未获得文件，最终失败，没有假成功。
- 临时语音角色闭环进一步发现 staging `MULTIMODAL_AUDIO_ENABLED=false`，白名单已是当前企业；Task `85b9760e-9c38-425c-bc7d-b0f7784e0a7e` 同样没有 TTS。模型创建了一份文本底稿，但可信完成检查拒绝将它冒充 MP3。临时角色 `c5480723-547c-4133-9745-58d612a53707` 已移除，原三个角色保留。
- 为完成本次语音正式接入，仅将该总开关改为 true，保留企业白名单和角色鉴权。配置发布 `audio54be172b6e1a26e4` 使用同一镜像/manifest，已 finished，九服务 healthy，Changes pending 已归零。
- 候选三份媒体测试文件及失败 staging 文本底稿 `d4883da7-eac2-43e0-8ae3-4f5d0386b22b` 已移入回收站，可恢复；只清理本轮明确记录的 E2E 文件。
- 仍待改善：能力无权或关闭时，能力检索应更准确地解释不可用，避免反复返回无关业务工具；不能靠给全部员工语音权限掩盖此问题。
- 代码审查另发现旧 `/multimodal/audio/understand` API 仍将 reasoning_content 输出给客户端，旧 `understand_file` 也有同类回退。本批统一主脑的媒体工具已禁用此回退，但尚未改旧 API；原生音频理解部署启用前必须一并收口，不得误报全平台已不存在该路径。

## 最终媒体与角色闭环

- 在开关生效后，root 真实登录创建仅有 `multimodal.speech.use`、`multimodal.audio.transcribe` 的临时自有数据范围角色 `aa822c2d-1359-4df0-8299-6898ebd8953d`，临时绑定 zhangsan。
- staging 真实浏览器 TTS + 同 Task ASR 通过：Task `03f013e7-56f6-4a28-9dcf-8a380d536b30`；MP3 `c0d444e6-0720-48e4-bf82-0bce6540e7c5`，27192 bytes，SHA256 `368b7c9a373c76a179c64c32d736ca75184857fce7780483c3554459d3ae29f0`。
- 音色设计通过：Task `7041f41f-00c8-40df-88a1-beb48325b50b`；MP3 `b01218c0-b5a8-4355-bf91-431a30b15e48`，30504 bytes。
- 阿里云生图 + 同 Task 识图通过：Task `a10c28a3-77ff-4aab-9605-ce378a7fa59e`；PNG `e7e156fb-d027-479d-ad64-4757727b2a64`，1039275 bytes。三份产物均刷新后从文件卡片真实下载并与版本哈希一致。
- 临时角色已解除绑定并删除，zhangsan 原三个角色保留；三份测试文件均进入回收站。撤权后新登录调用 `/multimodal/voices` 与 `/multimodal/audio/transcriptions` 分别返回 403，缺少 `multimodal.speech.use` / `multimodal.audio.transcribe`，没有创建语音任务。
- 用户随后询问录音按钮：代码路径为 MediaRecorder → 工作空间上传 → `/multimodal/audio/transcriptions` 异步任务 → 轮询 → 文字填回输入框，不自动发送。当前按钮未按语音权限预检；zhangsan 原角色缺少 ASR，确定会被后端拒绝。以上 ASR 验收是已有音频文件工具链，不冒充麦克风按钮完整验收。该入口体验与权限提示仍需收尾。
