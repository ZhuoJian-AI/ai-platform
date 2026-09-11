# 沉浸式前置：共享音频通道

基线 0fe16fc，延续 PLATFORM-VOICE-RELIABILITY-20260911，部署规则 c948cd2。

录音与朗读共享窗口级临时互斥事件：任一新操作先同步取消旧播放器和录音，再发起新请求。录音 generation 继续阻止迟到的麦克风/ASR 结果写回；pagehide 和卸载均取消录音，关闭轨道。没有持久化麦克风状态，没有新模型、接口或任务，没有扩大权限。

验证：node scripts/test-voice-channel.mjs 和 npm run typecheck 通过；git diff --check 通过。测试验证互斥信号和生命周期接线，不代替真实麦克风和浏览器完整语音回路。

尚未部署；未新增沉浸式入口。下一步仍需端点检测、转写自动提交同一 Task、最终消息自动朗读、暂停/退出控制与真实双视图验证。不能把这项前置修复称为沉浸式模式完成。

## 轮流对话控制器

新增 voiceConversation.ts：监听→转写→原有 Task 提交→最终消息朗读→再监听；每阶段检查 AbortSignal/generation，迟到结果不继续执行。待确认状态不重开麦，确认完成后保持暂停；TTS 失败不重跑提交。轻量 RMS 句末检测包含无语音超时和最长句子限制。

node scripts/test-voice-conversation.mjs 通过：重复启动、播放时不开麦、退出后的迟到录音、确认阻止、TTS 失败不重复提交、静音端点。npm run typecheck 通过。

这是控制器单元实现，尚未接入浏览器媒体适配器或 UI，不宣称真实自动对话闭环通过。仍须把既有录音/朗读逻辑复用为适配器，再接全局/侧栏统一入口并验收。没有部署本批。
