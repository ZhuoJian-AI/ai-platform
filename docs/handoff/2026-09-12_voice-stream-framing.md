# 分句播报基础实现（尚未接入运行链路）

任务 PLATFORM-VOICE-UX-20260912；延续现有认领，不改外部 Skill、子系统或权限。

已新增纯正文分句器 speech_segments.py：完整句子可在全文结束前交付，句号兼容小数跨 token；稳定序号和正文偏移不依赖 SSE 分块；限制单段长度、总段数及缓冲大小；取消后拒绝迟到数据；超限不部分推进状态。

验证：在 llm_router/backend 执行 `python -m unittest discover -s tests -p test_speech_segments_unit.py -v`，5 项通过；不启动数据库、不调用模型。git diff --check 通过。

关键发现：runner._consume_native 的 text 事件可被随后 text_retract 撤回，包括缺少业务写入回执、文件分析未验证和虚假成功声明。不能将原始 text_delta 无条件直接播放，也不能把已播语音视为可撤回。TaskMessage 目前在最终阶段才写入，不能提前假定 messageId 已存在。

下一步必须完成可信正文来源绑定、逐句 TTS 授权/计费/取消、有限合成队列及前端按序播放，并接通同 Task 首轮与页面提交链路。分句器本身不判断业务事实，必须只接收经过执行层确认可公开播报的正文；不得据此新增自然语言意图门禁。

状态：仅本地基础代码，不是用户可用的流式语音功能，不部署此未接通组件。线上仍为 source 1b646f4、manifest 3933010 的简化控制版本。
