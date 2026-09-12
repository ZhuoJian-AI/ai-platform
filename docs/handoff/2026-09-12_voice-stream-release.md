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

## 已部署与上线回归

- manifest：0d8ec7abb4379a0376bae7de9c94507673f958ee（PR #139）。
- Coolify deployment：voicefixdfe04359ea34e489，finished，configurationChanged=false。
- 实际运行 9 服务全部 healthy；backend、workspace-parser、storage-lifecycle、multimodal-worker 与 frontend 的镜像 digest、OCI revision 均符合上文。公网 /health 返回 ok，跨服务令牌一致。
- root 真实浏览器登录后进入 /monitor/router。
- e2e-deployed-voice-smoke.mjs 使用真正已部署的静态资源/API/主脑/TTS；只合成麦克风和 ASR 回填。单次业务提交、6 个 Run speech 请求、6 次真实音频 playing、随后继续监听，退出音轨释放。
- 测试 Task 84e4dc93-2970-4d43-9886-3ce43e25fbac 已经真实 UI 删除。首次脚本清理的精确菜单文本选择未匹配图标文字，改为名称正则后单独清理成功；未重复模型执行。测试脚本与发布证据在后续提交，不要求重新部署纯测试/文档。
- 无数据库迁移、无角色授权变更、无真实文件删除。该发布是语音批次完成，不代表全部业务可靠性计划完成。
