# 沉浸式前置：共享音频通道

基线 0fe16fc，延续 PLATFORM-VOICE-RELIABILITY-20260911，部署规则 c948cd2。

录音与朗读共享窗口级临时互斥事件：任一新操作先同步取消旧播放器和录音，再发起新请求。录音 generation 继续阻止迟到的麦克风/ASR 结果写回；pagehide 和卸载均取消录音，关闭轨道。没有持久化麦克风状态，没有新模型、接口或任务，没有扩大权限。

验证：node scripts/test-voice-channel.mjs 和 npm run typecheck 通过；git diff --check 通过。测试验证互斥信号和生命周期接线，不代替真实麦克风和浏览器完整语音回路。

尚未部署；未新增沉浸式入口。下一步仍需端点检测、转写自动提交同一 Task、最终消息自动朗读、暂停/退出控制与真实双视图验证。不能把这项前置修复称为沉浸式模式完成。

## 轮流对话控制器

新增 voiceConversation.ts：监听→转写→原有 Task 提交→最终消息朗读→再监听；每阶段检查 AbortSignal/generation，迟到结果不继续执行。待确认状态不重开麦，确认完成后保持暂停；TTS 失败不重跑提交。轻量 RMS 句末检测包含无语音超时和最长句子限制。

node scripts/test-voice-conversation.mjs 通过：重复启动、播放时不开麦、退出后的迟到录音、确认阻止、TTS 失败不重复提交、静音端点。npm run typecheck 通过。

这是控制器单元实现，尚未接入浏览器媒体适配器或 UI，不宣称真实自动对话闭环通过。仍须把既有录音/朗读逻辑复用为适配器，再接全局/侧栏统一入口并验收。没有部署本批。

## 浏览器接入

- 新增 browserVoiceAdapter 和 VoiceConversationPanel，终端顶部统一入口。必须先选择已有 Task，再主动开启；不创建独立语音任务。切换 Task/视图/页面安全退出，历史仍保留。
- 全局提交复用 runStream；页面通过注册当前 submit 回调复用 Bridge 上下文、文件引用、事件、确认卡片和刷新。错误不自动重发业务请求。等待确认保持麦克风关闭。
- 使用原有 recording/sign/complete/ASR、消息 ID 朗读接口，不传供应商秘密。合成音频短期 OSS 与生命周期沿用原实现。
- “结束本句”、暂停/停止、退出、静音均提供；朗读阻止时提示使用既有“朗读”按钮。静默 15 秒暂停，句末 1.2 秒及最长 60 秒；第一版阈值非复杂 VAD。
- npm run build 通过；两个控制器测试通过。test-voice-browser.mjs 在 Chrome 使用合成麦克风和替身 ASR/TTS 验证一轮提交、播放结束重开麦、旧轨道释放、退出全释放；不是模型或真人麦克风验收。
- 最初浏览器测试因 Vite 带时间戳模块与替身模块不是同一实例触发真实 401 跳转；修正测试导入路径后通过，没有修改产品鉴权。
- 尚无真人麦克风与真实子系统语音修改 E2E；这部分不能声称完成。发布记录随后补充。

## 发布阻断

Source e8b7a99c70b3f7dc47fb4ffb293ec48c5021f788 已 push，PR131 已创建。后续 gh 查询/合并连续 EOF，Git fetch TLS EOF，用户浏览器打开 PR 也返回 ERR_CONNECTION_CLOSED；不能确认合并，因此没有构建或更新部署清单。线上仍是 97d60a2 的角色授权版本，未部署本批语音模式。连接恢复后先确认 PR131 的实际状态，再按 Registry-first 发布，不重跑已通过的模型测试。

## 连接恢复与候选镜像

2026-09-12 11:36 网络恢复，重新获取部署规则 c948cd2；PR131 已合并，source SHA 为 6ce2a64cd4bce9e10bc6eed75fa122669339c058。复用已通过构建的相同前端源码产物，Registry 读取 digest 为 sha256:b15275cf82a746a7842bd7cb5bedaa5df97d09263d68506a872963fffae0a664。仅替换 frontend 镜像，后端与其他八个服务保持不变，无数据库迁移，无存储协议变化。Coolify 自动部署关闭、无待保存配置、无运行中部署；真实环境变量预检 PASS。部署及线上入口检查随后记录；此处不代表真实麦克风验收完成。

## staging 发布完成

- 仓库 https://github.com/ZhuoJian-AI/ai-platform；域名 https://ai-platform.staging.zhuojianai.com；Coolify Application jwbpxybciypgdidyzu2ebrlr。
- source 6ce2a64cd4bce9e10bc6eed75fa122669339c058 → frontend digest b15275cf82a746a7842bd7cb5bedaa5df97d09263d68506a872963fffae0a664 → manifest 29a05cf56a0b6ffe7f4eb0e479e145f212847e6b → deployment voicefix2666cfbae3285470 finished；运行容器镜像及 OCI revision 匹配。后端仍为 aa2c693 / 802300387bce73ea55c588bfdd4fa15f15462ecc25b935523e46289390c4f5d0。
- Registry-first、Compose PASS、真实环境变量 PASS、运行共享令牌一致、9 服务全部 healthy、无 Changes pending。容器替换期间短暂 502，完成后公网 /health 200。
- 管理员真实登录及角色语音能力页通过；员工真实登录、已有 Task 的语音入口、合成麦克风开启与退出释放全部轨道通过，无页面 JS 异常。首次浏览器访问受到本机代理影响；使用明确直连后通过，无产品鉴权修改。
- 没有重复调用模型；已通过的候选 ASR/TTS、OSS 证据复用。此次不代表真人麦克风、真实业务写入语音确认、多轮真实模型组合验收通过。
- 存储继续使用既有 signed-upload / Storage Gateway，两个 STORAGE 变量已配置，普通语音仍为临时媒体；无存储修改、无数据迁移、无数据库备份需求、无新长期工作空间文件或业务数据修改。
- 剩余：真人麦克风和真实子系统语音闭环、长回答完整口播摘要、未知写入受控核实、历史运行 401、chouchou 真实会话验收。第一版需先打开已有对话，切换页面/视图退出语音而不丢对话。

