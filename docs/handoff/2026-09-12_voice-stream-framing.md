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
