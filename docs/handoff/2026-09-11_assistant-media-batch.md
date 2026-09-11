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
