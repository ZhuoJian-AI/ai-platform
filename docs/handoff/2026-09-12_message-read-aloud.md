# 消息按需朗读（第二批收尾）

- 基线 `54bd7b8`，延续 PLATFORM-VOICE-RELIABILITY-20260911；部署规则 c948cd2。
- 替换旧的整段文本朗读弹层。总入口和页面侧栏使用同一 MessageSpeechButton，提交 Task/消息 ID；后端只取当前用户、当前企业的助手正文，客户端不能指定任意正文、模型、音色 ID 或地址。
- 复用 MultimodalJob、已验证的 text_to_speech 部署、获授权的标准音色和现有 worker/Storage Gateway；无新服务、依赖、表或独立 Task。
- 同一消息正文版本和音色版本复用有效任务，当前用户行锁串行化重复点击。排队执行、模型返回、上传后及读取结果均复查角色/消息/音色；内容或音色变化不播放旧缓存。
- 只处理正文，排除推理标签、代码、表格及链接地址；长正文朗读有限节选并明确提示查看全文，尚不是另一次模型生成的口播摘要。
- 播放支持停止、生成期间取消、切换/卸载清理、浏览器阻止播放后的手动入口；跨视图只允许一个播放者。不自动播放历史回复，不用浏览器内置 TTS。
- 普通朗读是临时 OSS 媒体，复用现有 workspace_upload_session_ttl_seconds 作为有效期，终态由音频 worker 回收；不会创建 WorkspaceFile 或 Artifact。明确生成 MP3 文件的原工具仍保留。

## 验证

- Python 3.12：`pytest --noconftest tests/test_message_speech_service.py -q`，9 passed；覆盖请求边界、正文过滤、所有者/权限/内容/音色/有效期及清理。它们是隔离单元测试，不声称数据库集成覆盖。
- 普通 pytest 因全局 conftest 要求未启动的本地 PostgreSQL 而在 setup 失败；未调整产品逻辑或全局 fixture 绕过集成验收。
- 受影响后端 Ruff、前端 typecheck 与 production build 通过；构建保留现有大 chunk 警告。
- `frontend/scripts/e2e-message-speech.mjs`：隔离候选环境 root/zhangsan 真实表单登录，临时标准音色仅授予现有测试角色，结束删除；未变更员工角色，也未修改 staging 配置。
- 标准音色使用小米官方内置 `mimo_default`，依据 https://mimo.mi.com/docs/usage-guide/speech-synthesis-v2.5 。候选的 text_to_speech 部署已经可用，未新增供应商密钥。
- 真实任务 `f87ecdf0-cb10-44b7-a82b-9a1879d9006d`：355152 字节音频、浏览器播放/停止、重复点击复用同一 job、工作空间文件 ID 集合不变。删除临时音色后 output_file_ref 已清空。
- 中途失败分别是候选缺标准音色、本地浏览器来源未配置、重启尚未就绪和测试选择器忽略图标可访问名称；前三项只修正隔离测试配置，后一项只修正脚本，没有为此放宽生产鉴权。
- 本批未覆盖真人麦克风、所有浏览器播放拒绝、并发撤权的真实端到端、完整侧栏往返播放；不以单元测试替代这些证据。

## 剩余与发布

- 本 source 提交时尚未部署本批；发布后补充 source/manifest/digest/Coolify 记录。
- staging zhangsan 当前 ASR/TTS 权限仍未授予，且没有可用标准音色；上线代码不会自动扩权，管理员需按业务决定授权和配置。
- 沉浸式轮流语音、未知写入核实与历史运行 401 仍未完成。

## 不可变镜像

- Source PR #125，`aa2c693d1c20ae967a40d19adf0f5ca75ef396cb`。
- Backend / parser / lifecycle / multimodal worker：`sha256:802300387bce73ea55c588bfdd4fa15f15462ecc25b935523e46289390c4f5d0`。
- Frontend：`sha256:eb814075436c25b192ff3eb95fee925b5ed9928d37a51e3dfc40cebf3e76e2a4`。
- Registry HEAD 均为 200 并返回上述 digest；构建 linux/amd64，OCI revision 均绑定 source。后端新模块镜像内 compileall 通过。
- 无迁移、无新增依赖；回切使用前一 manifest `3a1007885dd65b512c4b1b88393c674592522655` 的镜像，不回滚数据。构建使用既有镜像依赖层，不安装重型依赖。
