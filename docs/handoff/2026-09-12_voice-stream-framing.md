# 分句播报基础实现（尚未接入运行链路）

任务 PLATFORM-VOICE-UX-20260912；延续现有认领，不改外部 Skill、子系统或权限。

已新增纯正文分句器 speech_segments.py：完整句子可在全文结束前交付，句号兼容小数跨 token；稳定序号和正文偏移不依赖 SSE 分块；限制单段长度、总段数及缓冲大小；取消后拒绝迟到数据；超限不部分推进状态。

验证：在 llm_router/backend 执行 `python -m unittest discover -s tests -p test_speech_segments_unit.py -v`，5 项通过；不启动数据库、不调用模型。git diff --check 通过。

关键发现：runner._consume_native 的 text 事件可被随后 text_retract 撤回，包括缺少业务写入回执、文件分析未验证和虚假成功声明。不能将原始 text_delta 无条件直接播放，也不能把已播语音视为可撤回。TaskMessage 目前在最终阶段才写入，不能提前假定 messageId 已存在。

下一步必须完成可信正文来源绑定、逐句 TTS 授权/计费/取消、有限合成队列及前端按序播放，并接通同 Task 首轮与页面提交链路。分句器本身不判断业务事实，必须只接收经过执行层确认可公开播报的正文；不得据此新增自然语言意图门禁。

状态：仅本地基础代码，不是用户可用的流式语音功能，不部署此未接通组件。线上仍为 source 1b646f4、manifest 3933010 的简化控制版本。

## 后续：实际分句接口与播放队列（候选，未部署）

新增 GET /api/v1/multimodal/message-speech/plan，经过现有角色与消息归属检查，仅返回正文版本与句数。既有 POST message-speech 可携带 segment_index + expected_content_version；服务器自行从消息生成分句，不接受浏览器任意正文或供应商信息。每句沿用原语音任务、计费、临时 OSS、worker 再鉴权及清理；分句缓存互相隔离，旧全文朗读协议兼容。

沉浸式 speak 已改用此接口及最多两句的有序预取队列，播放前重新读取 job 以重查权限并刷新短签名；退出取消待处理任务，迟到创建结果也会取消，播放故障不重新提交业务。只有一条音轨播放，等待当前句播完才推进队列。

验证：前端 typecheck、build、test-voice-conversation.mjs、test-speech-playback-queue.mjs 通过；后端现有 Python 3.12 虚拟环境运行 test_message_speech_segments_unit.py 4 项通过，Ruff 通过。全局 Python 3.10 不支持现有 datetime.UTC，首次运行导入失败，不属于产品回归。未重复全量 CRUD、未调用真实模型。

重要边界：此版本仍等主脑回复落库后开始分句，尚不满足“全文生成完前首声播出”。长回复仍沿用明确标注的节选，尚未替换为语义口播摘要。不得单独发布前端（依赖本批后端接口）。接下来需要运行中可信正文流、Run/消息绑定，以及真实模型首声时间验收。

## 主脑文字流缓冲修复（候选，未部署）

发现 native._model_turn 原先收完供应商整轮文字后，stream_run 才一次发出 text_delta。新增最大 32 个事件的内部异步队列，供应商公开 text 立即传出；reasoning_content 仍仅在内部协议回传，工具调用仍等该模型轮完成后按原流程处理。非流式兜底不重复输出已有正文。消费者关闭时取消并收取 producer 结果，让网关原有 finally 负责用量结算；不增加主脑调用。

Python 3.12 环境：test_native_text_stream_unit.py 3 项通过（首段早于供应商结束、关闭时取消、失败不重发）；`pytest --noconftest tests/test_native_assistant_core.py -q` 40 项通过。这批均为无数据库/真实供应商调用的隔离测试；Ruff 通过。

尚需接 Run 绑定的可信可播报事件与 TTS 通道，不能把 text_delta 直接视作不可撤回的语音。当前新增链路仍未上线，不声称已实现真实首声早于全文完成。

## Run 级实时链路已接入候选代码（未部署，取代上述未接通状态）

- runner 在现有业务回执/分析证据允许时发布完整公开句子，文件交付等待最终提交。富文本不在未完成时播出；正文撤回会使语音片段失效。最终残句在 _finish 数据库提交后发布。长结果暂时停止于有限完整句子并提示看文字，语义摘要仍待完善。
- 新增 run-speech 接口以 Task、Run、segmentIndex、内容摘要定位服务端正文，浏览器不能提供任意文字、模型或供应商。每次检查 Task/Run 同租户同用户、有效角色，取消/错误运行拒绝旧音频；沿用原标准 TTS、计费及临时 OSS 生命周期。
- 语音 worker 是独立进程，不能读取 backend 内存注册表。因此可播报事件先持久化到 AgentRunEvent 再推送，既有 persist_run_events 按已有 seq 跳过已写事件；worker 从持久事件核验，backend 可读取 live handle。正文撤回及时持久化 reset。没有新增表或服务。
- 总入口、新 Task、页面侧栏均在各自本次 submit 回调内消费语音事件，不使用全局 DOM 事件或共享其他 Task 的监听器。LiveSpeechQueue 固定一个 Run，按片段序号去重，最多两句预取、单音轨播放；退出取消，迟到建 job 结果也取消。语音失败不重发业务。已经分句播放时禁止结尾再朗读全文。

验证：`node scripts/test-live-voice-stream.mjs` 用真实 adapter 代码加模拟 API/Audio 证明主脑 submit 尚未结束时首句播放、重放去重、顺序与一次业务提交；这是合成测试，不是 MiMo 实测。typecheck、test-speech-playback-queue.mjs、test-voice-conversation.mjs 通过。Python 3.12 环境 64 项聚焦测试通过（native、Run speech、message speech）；Ruff 通过。跨 worker 的持久读取目前为隔离测试，尚需真实数据库/worker 验收。

发布门禁仍未满足：真实 MiMo 首声时间、真实浏览器两轮播放/取消/跨页、数据库增量持久化及 worker 联调尚未验证。本候选禁止只发布前端或只更新 backend 而漏更新 multimodal-worker。线上继续保持 source 1b646f4 / manifest 3933010。未知写入管理核实、历史 401 和 chouchou 等既有事项不因本批变化视为完成。

## 后续取消边界修复

模型 provider 自行抛出 CancelledError 时，不会进入普通 Exception 分支，原队列消费者可能一直等不到结束事件。消费者现在同时等待队列及 producer，保留已经排队的正文，再传播取消；退出时收取临时读取任务，避免悬挂。聚焦 `pytest --noconftest tests/test_native_text_stream_unit.py tests/test_native_assistant_core.py -q` 44 项通过，Ruff 通过。仍未部署；上述真实供应商与跨 worker 验收门禁不变。

## 真实 PostgreSQL 持久化验收

本机 Docker 未启动，既有 PostgreSQL 服务停止；使用已安装程序建立仅监听 127.0.0.1:5459 的临时 voice_e2e 实例，未启动或修改既有数据库服务。新增 opt-in test_run_speech_postgres.py，强制检查本机端口与测试用户名，在随机独立 schema 创建 ORM 表，finally 删除该测试 schema。通过不同数据库连接调用实际 persist_run_events 与 owned_segment，并禁用内存 registry，验证增量落库可读、reset 后旧句 409、新句可读、重复 final 保存后 seq 仍为 [1,2,3,4]。

执行设置 VOICE_TEST_DATABASE_URL 后 `pytest --noconftest tests/test_run_speech_postgres.py -q`：1 passed（5.31s），Ruff 通过。测试 schema 已清理，临时 PostgreSQL 已停止。该证据为真实数据库/独立连接，不冒充实际 multimodal-worker 模型执行或浏览器播放。真实 MiMo 首声时序与浏览器联调仍待完成，未部署。

## 真实主脑、MiMo worker 与浏览器播报验收（2026-09-12）

源码 dbd2fe4；新建独立候选容器 ai-platform-voice-stream-dbd2fe4、独立 Redis 和数据库 ai_infra_voice_dbd2fe4，复制既有候选配置及数据库，未改 staging 或旧候选。启动 worker 前确认没有 queued/processing 历史任务。浏览器精确来源仅在候选 API 允许 http://127.0.0.1:4183；API 经 SSH 隧道访问，未开放公网端口。

新增 frontend/scripts/e2e-live-sentence-speech.mjs。使用环境变量凭据让 root、zhangsan 在隔离浏览器真实登录。候选快照缺少获授权标准音色，临时创建角色范围测试音色，finally 删除。真实 browserVoiceAdapter 连接真实 SSE 主脑、Run speech API、独立 worker、管理员配置的 mimo-v2.5-tts 和浏览器 HTMLAudioElement；无模拟 Audio、无伪造 Token。测试绕过 ASR 输入而直接传文字，浏览器允许自动播放，因此不替代麦克风、UI 点击或自动播放拒绝验收。

结果：29 个 speech_segment，29 次实际 playing；firstTextMs=27194、firstSoundMs=33801、finalMs=88869，runStatus=success、speechHandled=true。首声确实早于最终事件，不会结尾重读全文。计时包括创建 Task，firstText 是第一个 text 事件，不能单独视为供应商 TTFT。首声延迟仍有优化空间，不能承诺实时同结束。

测试 Task a3a8628d-3b95-4679-ae8d-85197b491ca8 已软删除；临时音色删除后既有 worker 生命周期回收了本轮 29 个临时音频，output_deleted=29、剩余引用=0，未动工作空间文件。脚本 node --check 通过，真实运行退出码 0。候选环境验证不代表已部署；跨页语音、取消/重连/播放拒绝，以及语义摘要与业务可靠性遗留项仍待完成。
