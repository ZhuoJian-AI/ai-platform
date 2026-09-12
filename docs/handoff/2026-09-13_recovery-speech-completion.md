# 同 Task 恢复、结果账本与语义口播

## 范围与行为

只修改 AI Platform 后端及项目文档，无前端、数据库迁移、外部 Skill、子系统或服务拓扑变化。基线 main `05a379a`；部署规则 `052b21a`。原 staging source `154f03d`、manifest `08b0fe1` 保持到本批正式发布。

普通写入匹配相同 Task 已持久化的请求引用，校验员工、企业、Action、参数摘要、页面及版本。查找不受模型最近对话窗口限制。仅匹配待确认、完成、执行中或未知结果；确定失败和过期确认不当作成功。原结果重读实时校验权限并保留原执行时间；旧参数已清空时拒绝猜测。每轮稳定操作 ID 不随模型 toolCallId 改变。确需重复操作使用独立 repeat 工具，并点击明确标记的新确认卡片。

按原 requestId 归并已经尝试的业务步骤，参数错误尚未形成持久请求时允许后续纠正。一个成功回执不能掩盖另一个未完成写入。查询、专业分析及最终文件交付分别进入消息结果账本，下一轮继续可读。账本不是自然语言目标分类器，也不声称能核实尚未调用的目标。

长回复或表格的口播在用户请求播放时才经管理员现有 chat 部署生成；不让文字聊天增加摘要请求。分句流保留最后一个序号给最终公开结果，按实际结果包括晚到的失败信息。超过输入预算、超时或无有效正文时明确提示查看文字，不编造摘要，不重跑业务。模型不得通过 reasoning_content 交付正文；临时音频仍沿用现有消息/版本/角色鉴权及生命周期。摘要缓存随消息内容和音色版本绑定，重复点击复用音频。

## 验证

```text
python -m pytest --noconftest tests/test_assistant_action_recovery.py tests/test_message_speech_service.py tests/test_run_speech_unit.py tests/test_message_speech_segments_unit.py tests/test_recovery_speech_completion.py tests/test_assistant_runner.py tests/test_operation_outcomes_runner.py -q
```

169 passed。覆盖真实事件消费器多项写入、错误后恢复、旧参数拒绝、确认标识、语义摘要失败降级、缓存和语音序号。既有 runner 测试漏计 speech_reset 的断言按现有安全行为补齐，未删除测试。

`VOICE_TEST_DATABASE_URL` 指向专用 loopback 5459 测试实例；`tests/test_recovery_history_postgres.py` 1 passed。验证 PostgreSQL JSONB 持久回执查找、其他 Task/员工隔离和参数差异，schema 在 finally 清理。未访问 staging 数据库。

真实模型服务验证：使用 zhangsan 当前有效角色和管理员现有部署，对虚构 E2E 输入生成摘要，正确输出业务修改成功而 Excel/OSS 保存失败、仅重试文件步骤。未调用业务 Action。此项是模型服务验证，不冒充真实浏览器业务闭环。

## 发布与剩余限制

2026-09-13 整批已部署：

- 仓库 `ZhuoJian-AI/ai-platform`，域名 `https://ai-platform.staging.zhuojianai.com`，Coolify Application `jwbpxybciypgdidyzu2ebrlr`。
- source `5ca01e726208f9cf2fd02702c2bd5116be1b7439`（PR #172）；manifest `b751c05d03419585aa7ac4c550e0834a26f28267`（PR #173）。
- backend 与三个共享 worker 镜像 `sha256:13e7c6dbec8232d4781210523843ac74c937c8b21be3b3d93f177e01234de253`；运行镜像与 OCI source 标签一致。前端沿用 `28dcfbd`，未修改前端。
- Registry-first 构建与 compileall 通过，Compose PASS；真实运行变量齐全、共享令牌一致，无待发布配置或并行部署。Coolify `voicefix6dc92e4a3def0a8e` finished，9 服务 healthy，公开 health 200。
- 发布后浏览器调用与重连均返回 `Transport closed`。本批 root/zhangsan 页面、长回复播放及真实业务恢复没有新的通过证据，仍待连接恢复后验收。
- 临时 PostgreSQL 容器与本机隧道已停止并移除；只使用独立测试数据，未碰 staging 数据库。临时构建文件的清理命令被工具策略拦截，未执行；约 2.5 MB 的专用 `/tmp/ai-platform-recovery-build-5ca01e7` 及本批临时源码文件保留，不包含密钥或用户数据。活动和回滚镜像保留。

- 需补最终管理员/员工浏览器业务恢复及长回复播放结果。
- 不为缺失历史参数补造证据；旧记录需要核实。
- chouchou 真实会话、204A231 图片接口、历史 401 原始证据仍受外部条件限制。
- 无数据库迁移；OSS 原始文件和工作空间链路未改，不重复全量文件测试。
