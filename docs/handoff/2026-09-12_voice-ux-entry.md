# 语音模式入口与按轮定位

任务 PLATFORM-VOICE-UX-20260912，基线 21d7bff，部署规则 c948cd2。

将唯一语音控制器提升为终端 Provider，三个输入框使用同一控制器。语音按钮移到发送按钮旁，新会话首次转写复用既有新建/运行流程，保留文件和配置。自身创建的 Task 允许接续控制器；同 Task 的页面切换保持控制器，其他 Task 或新草稿退出。

聊天和侧栏按用户轮次数定位一次，后续正文变化不触发滚动；增加回到当前回复。侧栏动画结束也定位当前轮。

验证：npm run typecheck、npm run build 通过；test-voice-conversation.mjs、test-voice-channel.mjs 通过；test-voice-ux.mjs 的真实浏览器组件测试通过定位/自由滚动/手动返回/草稿可用；test-voice-ux-candidate.mjs 通过真实 zhangsan 登录、候选入口、合成麦克风开关/轨道释放、无空任务导航、无页面异常。候选测试复用 staging API，不触发模型调用，不代表真人首句和跨页业务操作验收。

尚未合并部署。分句流式 TTS、未知写入核实、多目标状态、历史 401 证据审查及 chouchou 专项继续待做。已知边界：当前定位使用同 Task 最新用户轮次，未扩展导航协议为显式消息 ID。

## 发布完成（后续记录取代上述候选状态）

PR134 源码合并为 7d93aba7247b4a27a5b08e525ad4d92f33b5e490；PR135 manifest 为 3310ac6cab7190354e2e315db21a200595ee258c。前端 Registry digest 为 sha256:88c98f57ee2ef151205eb4471477de236bd6e1f57adb36ef663627d74ca9c688；Coolify deployment voicefix1257e4d735890d81 finished，运行镜像/OCI revision 一致，无 Changes pending，9 服务 healthy，共享令牌一致。公网 /health 200；替换容器期间曾短暂503，完成后恢复。

E2E_ONLINE=1 node scripts/test-voice-ux-candidate.mjs 跳过本地静态资源替换，真实 staging 员工登录、新会话语音入口、合成麦克风开关、轨道释放、无空任务导航和无页面 JS 异常通过。没有再次调用模型。尚不能声明首句 ASR 自动建 Task 或跨页语音完整回路的线上专项验收。

目标 https://ai-platform.staging.zhuojianai.com，仓库 ZhuoJian-AI/ai-platform；只变更该应用前端，无数据库迁移及存储修改。发布规则 c948cd2。流式播报与其他可靠性收尾继续待做。

## 简化控制（候选，尚未部署）

用户反馈操作复杂后，将常驻控制收口为状态、暂停/继续、退出；设置弹层仅保留静音和结束本句。关闭状态点击语音模式直接启动，不再打开重复开启按钮。普通录音入口改名语音输入并说明检查后发送。类型检查及原控制器测试通过，尚需生产构建和候选按钮回归后发布；本修改仍不包含流式 TTS。

## 简化控制已发布（取代上一节候选状态）

2026-09-12：生产构建、候选真实员工按钮回归通过后，PR136 合并 source `1b646f47707ca50438a282337c8ab0cafd203c9f`。Registry 镜像 `sha256:4f6646cce4199185a9904371461830c1bae98d74b9ea4aae7a34f9deb83f82ae`，PR137 manifest `3933010c1b60f70f3e05c228ec7952bb5097603e`，Coolify deployment `voicefix2cf6f53310c98791` finished。

运行容器 digest/OCI revision 一致；9 服务 healthy、真实必填环境值齐全、共享令牌一致，无 Changes pending。Compose validator PASS。公网 /health 返回 ok。替换容器期间短暂 Bad Gateway，部署完成后恢复。

在 frontend 目录执行 `E2E_ONLINE=1 node scripts/test-voice-ux-candidate.mjs`：线上真实 zhangsan 登录、草稿一键语音入口、合成麦克风开启与退出、全部轨道释放、无空任务导航、无页面异常通过。凭据仅通过进程环境传入，不保存报告或仓库。没有重复模型测试；不代表首句 ASR、跨页业务确认及真人语音全部通过。

本批仅前端更新，不改数据库、存储、模型部署或权限。规则版本 c948cd2。分句流式播报、未知写入受控核实及其他既有专项限制仍待完成。
