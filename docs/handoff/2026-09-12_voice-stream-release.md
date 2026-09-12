# 分句语音发布

- source：1999b1bf4b10e2762e139ec0d0ac4a96a8b886f3（PR #138）。
- backend、workspace-parser、storage-lifecycle、multimodal-worker：sha256:c52a131b5ac63b5bb25b010cd922ffd7deb8548574e958cdbe6ad53629bb8f44。
- frontend：sha256:a6357c73911fb6ad7bf4dd41489a9b57855b0efbc3752908a48f326c86055ee7。
- Registry 远端 HEAD 确认摘要；构建使用现有锁定依赖镜像，仅复制 source app 与已验证 dist。未改变依赖，无数据库迁移。
- 前端生产构建通过；镜像内 Python compileall 通过。其余验收证据见 voice-stream-framing 交接，包含真实 MiMo/数据库、staging 来源候选前端真实嵌入、共享 Task、自由滚动与退出音轨释放。
- 发布前当前部署为 3933010、9 服务 healthy、跨服务 Token 一致、必要变量非空、Auto Deploy=false、Changes pending=false。
- 旧摘要保留在上一 manifest，可回退；不删除任何业务数据和镜像。
- 本文件提交时镜像就绪，尚未触发本批部署。部署 ID 与上线回归另行记录，不把构建视为上线。
- 规则版本：c948cd20bc23e64d1d53596ce49699c525351284。
- 遗留：长回复语义口播摘要、未知写入管理核实、部分成功恢复、历史 401、chouchou 真实会话与子系统图片接口限制，均不因本批发布视为完成。
